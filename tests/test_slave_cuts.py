import itertools
import operator

import cplex
import pytest

from models.column_generation.orchestrator_services import (
    add_no_good_cut,
    calculate_slice_height,
)
from models.column_generation.slave_problem import create_slave_model
from models.common.position_generator import generate_positions_xym


PLACEMENTS = ["z_x_0_0", "z_x_1_0", "z_y_2_0"]
PATTERNS = list(itertools.product((0, 1), repeat=len(PLACEMENTS)))
REFERENCE_ROW = ["z_x_0_0", "z_x_13_0", "z_x_26_0"]
REFERENCE_MIXED = REFERENCE_ROW + ["z_y_39_0"]


def configure_model(model):
    for setter in (
        model.set_log_stream, model.set_error_stream,
        model.set_warning_stream, model.set_results_stream,
    ):
        setter(None)
    model.parameters.timelimit.set(1)
    model.parameters.threads.set(1)
    return model


@pytest.fixture
def placement_model():
    model = configure_model(cplex.Cplex())
    names = PLACEMENTS + ["s_0", "s_1"]
    model.variables.add(names=names, types=["B"] * len(names))
    yield model
    model.end()


def satisfies_cuts(model, values):
    comparisons = {"L": operator.le, "G": operator.ge, "E": operator.eq}
    return all(
        comparisons[sense](
            sum(coefficient * values[index] for index, coefficient in zip(row.ind, row.val)),
            rhs,
        )
        for row, sense, rhs in zip(
            model.linear_constraints.get_rows(),
            model.linear_constraints.get_senses(),
            model.linear_constraints.get_rhs(),
        )
    )


@pytest.mark.parametrize("excluded", PATTERNS)
def test_cut_excludes_only_the_placement_pattern(placement_model, excluded):
    active = [name for name, value in zip(PLACEMENTS, excluded) if value]
    add_no_good_cut(placement_model, active, 0)

    for pattern in PATTERNS:
        for window in (0, 1):
            values = pattern + (window, 1 - window)
            assert satisfies_cuts(placement_model, values) == (pattern != excluded)


def test_auxiliary_active_variables_do_not_change_the_excluded_column(placement_model):
    add_no_good_cut(placement_model, [PLACEMENTS[0], "s_0"], 0)

    for pattern in PATTERNS:
        for window in (0, 1):
            assert satisfies_cuts(placement_model, pattern + (window, 1 - window)) == (
                pattern != (1, 0, 0)
            )


def test_accumulated_cuts_preserve_other_patterns(placement_model):
    excluded = {(1, 0, 0), (0, 1, 0)}
    for cut_id, pattern in enumerate(sorted(excluded)):
        active = [name for name, value in zip(PLACEMENTS, pattern) if value]
        add_no_good_cut(placement_model, active, cut_id)

    for pattern in PATTERNS:
        assert satisfies_cuts(placement_model, pattern + (1, 0)) == (pattern not in excluded)


@pytest.mark.parametrize("selected,with_cut,expected_feasible", [
    (REFERENCE_ROW, False, True),
    (REFERENCE_MIXED, False, True),
    (REFERENCE_ROW, True, False),
    (REFERENCE_MIXED, True, True),
    (REFERENCE_ROW[:2], True, True),
    (REFERENCE_ROW[:2] + ["z_y_39_0"], True, True),
], ids=["row", "mixed", "excluded-row", "superset", "subset", "same-cardinality"])
def test_reference_pricing_geometry(selected, with_cut, expected_feasible):
    xy_x, xy_y = generate_positions_xym(50, 20, 13, 8)
    slice_height = calculate_slice_height(50, 20, 13, 8)
    model = configure_model(create_slave_model(
        1, xy_x, xy_y, {"pi": {}}, 50, 8, 13, 20, slice_height,
    ))
    try:
        if with_cut:
            add_no_good_cut(model, REFERENCE_ROW, 0)
        names = [
            name for name in model.variables.get_names()
            if name.startswith("z_x_") or name.startswith("z_y_")
        ]
        assert set(selected) <= set(names)
        bounds = [(name, float(name in selected)) for name in names]
        model.variables.set_lower_bounds(bounds)
        model.variables.set_upper_bounds(bounds)
        model.solve()

        assert model.solution.is_primal_feasible() == expected_feasible
        assert model.solution.get_status() == (101 if expected_feasible else 103)
    finally:
        model.end()
