"""Regression coverage for optional selection in the rotated PS comparator."""

from itertools import combinations
from multiprocessing import get_context

import pytest

cplex = pytest.importorskip("cplex")

from models.comparative import pisinger_sigurd_2005_rotation as ps
from utils import execution_runner
from utils.execution_result import ExecutionResult
from utils.paver_constants import PaverConstants as PAVER
from utils.status_normalizer import map_cplex_lp_status


NO_FIT_CASES = [
    (5, 5, 6, 1),   # Multiple candidates despite the lack of placements.
    (5, 5, 11, 1),  # The original LP is also infeasible.
    (2, 2, 3, 2),   # The area bound is already zero.
    (2, 2, 3, 1),   # One candidate; the original LP has value one.
]
FIT_CASES = [
    pytest.param((4, 3, 4, 2), 1, id="only-original"),
    pytest.param((2, 3, 3, 2), 1, id="only-rotated"),
    pytest.param((5, 5, 3, 2), 4, id="mixed-orientations"),
    pytest.param((5, 5, 2, 3), 4, id="tall-item"),
    pytest.param((4, 4, 2, 2), 4, id="square"),
    pytest.param((3, 7, 3, 2), 3, id="tall-bin"),
    pytest.param((5, 4, 3, 2), 3, id="unused-area"),
]


def make_instance(dimensions):
    return dict(zip(
        ("bin_width", "bin_height", "item_width", "item_height"), dimensions
    ), case_name="ps_rotation_regression")


@pytest.fixture
def configure_instance(monkeypatch):
    def configure(dimensions):
        instance = make_instance(dimensions)
        for field, value in instance.items():
            monkeypatch.setattr(ps, field.upper(), value)
        return instance
    return configure


@pytest.fixture
def spawn_context(monkeypatch):
    monkeypatch.setattr(execution_runner, "multiprocessing", get_context("spawn"))


def configure_solver(model):
    for stream in ("results", "log", "warning", "error"):
        getattr(model, "set_" + stream + "_stream")(None)
    model.parameters.timelimit.set(5)
    model.parameters.threads.set(1)
    model.parameters.randomseed.set(0)


def selected_layout(model, dimensions):
    """Read actual selection variables, including models with no candidates."""
    values = dict(zip(model.variables.get_names(), model.solution.get_values()))
    width, height = dimensions[2:]
    layout = []
    for name, value in values.items():
        if name.startswith("f_") and value > 0.5:
            index = name[2:]
            rotated = values["r_" + index] > 0.5
            w, h = (height, width) if rotated else (width, height)
            layout.append((values["x_" + index], values["y_" + index], w, h))
    return layout


def assert_geometry(layout, dimensions, expected):
    width, height, item_width, item_height = dimensions
    tolerance = 1e-6
    assert len(layout) == expected
    for x, y, w, h in layout:
        assert (w, h) in ((item_width, item_height), (item_height, item_width))
        assert x >= -tolerance and y >= -tolerance
        assert x + w <= width + tolerance
        assert y + h <= height + tolerance
    for a, b in combinations(layout, 2):
        assert (a[0] + a[2] <= b[0] + tolerance
                or b[0] + b[2] <= a[0] + tolerance
                or a[1] + a[3] <= b[1] + tolerance
                or b[1] + b[3] <= a[1] + tolerance)


def assert_optimal_result(result, expected):
    assert isinstance(result, ExecutionResult)
    assert result.case_name == "ps_rotation_regression"
    assert result.model_name == ps.MODEL_NAME
    assert result.model_status == PAVER.MODEL_STATUS_OPTIMAL
    assert result.termination_status == PAVER.TERMINATION_NORMAL
    assert result.objective_value == pytest.approx(expected)
    assert result.error_message is None


def assert_lp_value(model, expected):
    with cplex.Cplex(model) as lp:
        configure_solver(lp)
        # Relax all discrete variables, including coordinates and orientation.
        lp.set_problem_type(lp.problem_type.LP)
        lp.solve()
        status = map_cplex_lp_status(
            lp.solution.get_status(), lp.solution.is_primal_feasible()
        )
        assert status.has_feasible_solution
        assert status.model_status == PAVER.MODEL_STATUS_OPTIMAL
        assert status.termination_status == PAVER.TERMINATION_NORMAL
        assert lp.solution.get_objective_value() == pytest.approx(expected)


@pytest.mark.parametrize("dimensions", NO_FIT_CASES)
def test_no_feasible_orientation_has_zero_mip_lp_and_empty_layout(
    configure_instance, dimensions
):
    configure_instance(dimensions)
    width, height, item_width, item_height = dimensions
    assert ps.calculate_physical_item_bound() == (
        width * height // (item_width * item_height)
    )
    with ps.create_model(5) as model:
        configure_solver(model)
        assert_optimal_result(ps.solve_model(model), 0)
        layout = selected_layout(model, dimensions)
        assert layout == []
        assert_geometry(layout, dimensions, 0)
        assert_lp_value(model, 0)


@pytest.mark.parametrize("dimensions, expected", FIT_CASES)
def test_fit_preserves_optimum_lp_geometry_and_optional_selection(
    configure_instance, dimensions, expected
):
    configure_instance(dimensions)
    with ps.create_model(5) as model:
        configure_solver(model)
        assert_optimal_result(ps.solve_model(model), expected)
        assert_geometry(selected_layout(model, dimensions), dimensions, expected)
        # Preserve the area-bound LP control when an orientation fits.
        assert_lp_value(model, ps.calculate_physical_item_bound())
        model.variables.set_upper_bounds([
            (name, 0.0) for name in model.variables.get_names()
            if name.startswith("f_")
        ])
        assert_optimal_result(ps.solve_model(model), 0)
        assert selected_layout(model, dimensions) == []


@pytest.mark.parametrize("dimensions, expected", [
    *((dimensions, 0) for dimensions in NO_FIT_CASES),
    ((4, 3, 4, 2), 1),
    ((2, 3, 3, 2), 1),
    ((5, 5, 3, 2), 4),
])
def test_public_api_with_explicit_instance_and_spawn(spawn_context, dimensions, expected):
    result = ps.execute_with_time_limit(10, make_instance(dimensions))
    assert_optimal_result(result, expected)
    assert 0 < result.total_time_s < 10


@pytest.mark.parametrize("field", (
    "bin_width", "bin_height", "item_width", "item_height"
))
@pytest.mark.parametrize("value", [0, -1, 1.5, True, "1", None])
def test_invalid_dimensions_are_rejected_before_empty_domain(
    configure_instance, monkeypatch, field, value
):
    configure_instance((5, 5, 6, 1))
    monkeypatch.setattr(ps, field.upper(), value)
    with pytest.raises(ValueError, match=field):
        ps.create_model(5)


@pytest.mark.parametrize("dimensions", [(0, 5, 6, 1), (5, 5, -1, 1)])
def test_public_api_reports_invalid_dimensions_as_errors(spawn_context, dimensions):
    result = ps.execute_with_time_limit(10, make_instance(dimensions))
    assert result.termination_status == PAVER.TERMINATION_ERROR
    assert result.objective_value is None
    assert result.error_message
