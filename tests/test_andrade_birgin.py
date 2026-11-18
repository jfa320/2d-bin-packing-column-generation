"""Selection regressions for the center-based Andrade--Birgin Big-M model."""

from functools import lru_cache
from itertools import combinations, product
from multiprocessing import get_context

import pytest

cplex = pytest.importorskip("cplex")

from models.comparative import andrade_birgin_2013 as ab
from models.comparative.andrade_birgin_2013_model import AndradeBirgin2013ModelBuilder
from utils import execution_runner
from utils.paver_constants import PaverConstants as PAVER


def make_model(dimensions):
    model = AndradeBirgin2013ModelBuilder(*dimensions).build(5)
    for stream in ("results", "log", "warning", "error"):
        getattr(model, "set_" + stream + "_stream")(None)
    model.parameters.threads.set(1)
    model.parameters.randomseed.set(0)
    return model


def fix_variables(model, values):
    bounds = list(values.items())
    model.variables.set_lower_bounds(bounds)
    model.variables.set_upper_bounds(bounds)


def assert_geometry(model, dimensions, expected):
    width, height, item_width, item_height = dimensions
    values = dict(zip(model.variables.get_names(), model.solution.get_values()))
    layout = []
    tolerance = 1e-6
    for name, value in values.items():
        if not name.startswith("f_") or value < 0.5:
            continue
        index = name[2:]
        rotated = values["r_" + index] > 0.5
        w, h = (item_height, item_width) if rotated else (item_width, item_height)
        assert values["w_" + index] == pytest.approx(w)
        assert values["h_" + index] == pytest.approx(h)
        x, y = values["cx_" + index] - w / 2, values["cy_" + index] - h / 2
        assert -tolerance <= x and x + w <= width + tolerance
        assert -tolerance <= y and y + h <= height + tolerance
        layout.append((x, y, w, h))
    assert len(layout) == expected
    assert model.solution.get_objective_value() == pytest.approx(expected)
    for a, b in combinations(layout, 2):
        assert (a[0] + a[2] <= b[0] + tolerance
                or b[0] + b[2] <= a[0] + tolerance
                or a[1] + a[3] <= b[1] + tolerance
                or b[1] + b[3] <= a[1] + tolerance)


def enumerated_capacity(width, height, item_width, item_height):
    """Independent exhaustive cell-mask packing for small integer dimensions."""
    full = (1 << (width * height)) - 1
    covering = [[] for _ in range(width * height)]
    for w, h in {(item_width, item_height), (item_height, item_width)}:
        for y in range(height - h + 1):
            for x in range(width - w + 1):
                cells = [j * width + i for j in range(y, y + h)
                         for i in range(x, x + w)]
                mask = sum(1 << cell for cell in cells)
                for cell in cells:
                    covering[cell].append(mask)

    @lru_cache(None)
    def search(unavailable):
        free = full ^ unavailable
        if not free:
            return 0
        first = free & -free
        best = search(unavailable | first)
        for mask in covering[first.bit_length() - 1]:
            if not unavailable & mask:
                best = max(best, 1 + search(unavailable | mask))
        return best

    return search(0)


def test_optional_selection_counterexample():
    dimensions = (3, 3, 2, 2)
    assert AndradeBirgin2013ModelBuilder(*dimensions).physical_item_bound() == 2
    with make_model(dimensions) as model:
        model.solve()
        assert model.solution.get_status() == 101
        assert_geometry(model, dimensions, 1)


@pytest.mark.parametrize("dimensions", [
    (3, 3, 2, 2), (1, 9, 2, 2), (5, 5, 11, 1), (2, 2, 3, 3),
])
def test_empty_selection_is_feasible_even_when_candidates_do_not_fit(dimensions):
    with make_model(dimensions) as model:
        fix_variables(model, {n: 0.0 for n in model.variables.get_names()
                              if n.startswith("f_")})
        model.solve()
        assert model.solution.get_status() == 101
        assert_geometry(model, dimensions, 0)


@pytest.mark.parametrize("selected", [1, 2])
@pytest.mark.parametrize("bits", product((0, 1), repeat=2))
def test_unselected_item_can_coincide_with_selected_for_every_branch(selected, bits):
    dimensions = (3, 3, 2, 2)
    with make_model(dimensions) as model:
        fix_variables(model, {
            "f_1": int(selected == 1), "f_2": int(selected == 2),
            "cx_1": 1.0, "cy_1": 1.0, "cx_2": 1.0, "cy_2": 1.0,
            "q_1,2": bits[0], "q_2,1": bits[1],
        })
        model.solve()
        assert model.solution.get_status() == 101
        assert_geometry(model, dimensions, 1)


@pytest.mark.parametrize("coordinate, value", [
    ("cx_1", 0), ("cx_1", 3), ("cy_1", 0), ("cy_1", 3),
])
def test_selected_item_cannot_protrude_from_any_side(coordinate, value):
    with make_model((3, 3, 2, 2)) as model:
        fix_variables(model, {"f_1": 1, "f_2": 0, coordinate: value})
        model.solve()
        assert model.solution.get_status() == 103


def test_selected_items_cannot_overlap():
    with make_model((3, 3, 2, 2)) as model:
        fix_variables(model, {"f_1": 1, "f_2": 1})
        model.solve()
        assert model.solution.get_status() == 103


@pytest.mark.parametrize("bits, centers", [
    ((0, 0), (3, 1, 1, 1)),
    ((1, 1), (1, 1, 3, 1)),
    ((1, 0), (1, 3, 1, 1)),
    ((0, 1), (1, 1, 1, 3)),
])
def test_selected_pair_preserves_each_original_big_m_branch(bits, centers):
    dimensions = (4, 4, 2, 2)
    with make_model(dimensions) as model:
        fixed = dict(zip(("cx_1", "cy_1", "cx_2", "cy_2"), centers))
        fixed.update({"f_1": 1, "f_2": 1, "f_3": 0, "f_4": 0,
                      "q_1,2": bits[0], "q_2,1": bits[1]})
        fix_variables(model, fixed)
        model.solve()
        assert model.solution.get_status() == 101
        assert_geometry(model, dimensions, 2)


def test_mixing_orientations_improves_the_packing():
    dimensions = (3, 3, 2, 1)
    with make_model(dimensions) as model:
        model.solve()
        assert model.solution.get_status() == 101
        assert_geometry(model, dimensions, 4)
        fix_variables(model, {n: 0 for n in model.variables.get_names()
                              if n.startswith("r_")})
        model.solve()
        assert model.solution.get_status() == 101
        assert_geometry(model, dimensions, 3)


@pytest.mark.parametrize("width, height", product(range(1, 5), repeat=2))
def test_small_mip_and_lp_match_independent_packing_bounds(width, height):
    for w, h in product(range(1, 5), repeat=2):
        dimensions = (width, height, w, h)
        expected = enumerated_capacity(*dimensions)
        with make_model(dimensions) as model:
            model.solve()
            assert model.solution.get_status() == 101, dimensions
            assert_geometry(model, dimensions, expected)
            # Relax every binary, preserving its [0, 1] domain. The LP may
            # remain weaker than the integer geometry, including no-fit cases.
            model.set_problem_type(model.problem_type.LP)
            model.solve()
            assert model.solution.get_status() == 1, dimensions
            lp_value = model.solution.get_objective_value()
            area_bound = width * height // (w * h)
            assert expected - 1e-6 <= lp_value <= area_bound + 1e-6, dimensions


@pytest.mark.parametrize("dimensions, expected", [
    ((3, 3, 2, 2), 1), ((1, 9, 2, 2), 0), ((3, 2, 2, 3), 1),
])
def test_public_api_with_explicit_instance_and_spawn(monkeypatch, dimensions, expected):
    monkeypatch.setattr(execution_runner, "multiprocessing", get_context("spawn"))
    instance = dict(zip(
        ("bin_width", "bin_height", "item_width", "item_height"), dimensions,
    ), case_name="andrade_selection_regression")
    result = ab.execute_with_time_limit(10, instance)
    assert result.case_name == instance["case_name"]
    assert result.model_name == ab.MODEL_NAME
    assert result.model_status == PAVER.MODEL_STATUS_OPTIMAL
    assert result.termination_status == PAVER.TERMINATION_NORMAL
    assert result.objective_value == pytest.approx(expected)
    assert result.error_message is None
