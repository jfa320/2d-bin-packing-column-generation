"""Isolated Beasley MIPs, independent geometric oracles and solver-state tests."""

from fractions import Fraction
from itertools import combinations
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

cplex = pytest.importorskip("cplex")

from models.quadrant_column_generation import (
    Placement, Quadrant, build_quadrants, generate_global_discretization,
)
from models.quadrant_column_generation.beasley_model import (
    BeasleyModel, BeasleyModelBuilder,
)
from utils.paver_constants import PaverConstants as PAVER


def make_builder(dimensions, quadrant_index=4, alpha=0.8):
    grid = generate_global_discretization(*dimensions)
    result = build_quadrants(*dimensions, alpha=alpha)
    assert result.applicable
    quadrant = result.quadrants[quadrant_index - 1]
    return grid, quadrant, BeasleyModelBuilder(grid, quadrant)


def disjoint(a, b):
    # Independent from Phase A's coverage/overlap implementations.
    return (a.x + a.width <= b.x or b.x + b.width <= a.x
            or a.y + a.height <= b.y or b.y + b.height <= a.y)


def exhaustive_count(placements):
    """Enumerate every subset, checking geometric rectangles, not model rows."""
    assert len(placements) <= 12
    best = 0
    for mask in range(1 << len(placements)):
        count = mask.bit_count()
        if count <= best:
            continue
        selected = [p for index, p in enumerate(placements) if mask & (1 << index)]
        if all(disjoint(a, b) for a, b in combinations(selected, 2)):
            best = count
    return best


def assert_unit_solution(result, expected, grid, quadrant):
    assert result.error_message is None
    assert result.status.model_status == PAVER.MODEL_STATUS_OPTIMAL
    assert result.status.termination_status == PAVER.TERMINATION_NORMAL
    assert result.status.has_feasible_solution
    assert result.proven_optimal
    assert result.objective_value == pytest.approx(expected)
    assert len(result.placements) == expected
    assert len(set(result.placements)) == expected
    assert result.best_bound == pytest.approx(expected)
    assert result.solve_time_s >= 0
    assert all(grid.contains_placement(p) for p in result.placements)
    assert all(quadrant.contains_placement(p) for p in result.placements)
    assert all(disjoint(a, b) for a, b in combinations(result.placements, 2))


@pytest.mark.parametrize("quadrant_index, expected", [(1, 25), (2, 5), (3, 5), (4, 1)])
def test_square_optima_known_by_counting_distinct_unit_cells(quadrant_index, expected):
    grid, quadrant, builder = make_builder((6, 6, 1, 1), quadrant_index)
    with builder.build(time_limit_s=2) as model:
        assert len(model.placements) == expected
        assert all(not p.rotated for p in model.placements)
        result = model.solve()
    assert_unit_solution(result, expected, grid, quadrant)


@pytest.mark.parametrize("dimensions, expected, required_orientation", [
    ((11, 11, 2, 1), 2, None),
    ((16, 11, 2, 1), 3, True),
    ((11, 16, 2, 1), 3, False),
    ((16, 11, 1, 2), 3, False),
])
def test_small_unit_optima_and_both_input_orientations(dimensions, expected, required_orientation):
    grid, quadrant, builder = make_builder(dimensions)
    with builder.build(time_limit_s=2) as model:
        assert {p.rotated for p in model.placements} == {False, True}
        result = model.solve()
    assert_unit_solution(result, expected, grid, quadrant)
    if required_orientation is not None:
        # A 3x2 usable rectangle needs a vertical item to reach three; the
        # transposed 2x3 rectangle needs a horizontal item.
        assert any(p.rotated == required_orientation for p in result.placements)


@pytest.mark.parametrize("dimensions, quadrant_index, alpha, expected", [
    ((6, 6, 1, 1), 2, 0.8, 5),
    ((11, 11, 2, 1), 4, 0.8, 2),
    ((16, 11, 2, 1), 4, 0.8, 3),
    ((11, 16, 2, 1), 4, 0.8, 3),
    ((16, 16, 6, 4), 4, Fraction(1, 2), 2),
])
def test_cplex_matches_exhaustive_geometric_enumeration(
    dimensions, quadrant_index, alpha, expected,
):
    grid, quadrant, builder = make_builder(dimensions, quadrant_index, alpha)
    with builder.build(time_limit_s=2) as model:
        exact = exhaustive_count(model.placements)
        result = model.solve()
    assert exact == expected
    assert_unit_solution(result, exact, grid, quadrant)


@pytest.mark.parametrize("dimensions, origin, reference_size", [
    ((16, 11, 2, 1), (13, 9), (3, 2)),
    ((11, 16, 2, 1), (9, 13), (2, 3)),
])
def test_quadrant_matches_full_beasley_and_existing_andrade_birgin(
    dimensions, origin, reference_size,
):
    from models.comparative.andrade_birgin_2013_model import AndradeBirgin2013ModelBuilder

    grid, quadrant, builder = make_builder(dimensions)
    # These gcd=1 cases have all integer corners. Thus their global Q4
    # placement universe is exactly a translated 3x2 (or 2x3) full pallet.
    # This separate reference does not regenerate the tested quadrant's grid.
    width, height = reference_size
    reference_grid = generate_global_discretization(width, height, 2, 1)
    full_pallet = Quadrant(1, Fraction(0), Fraction(0), Fraction(width),
                          Fraction(height), True, True)
    translated = {
        Placement(p.x - origin[0], p.y - origin[1], p.width, p.height, p.rotated)
        for p in grid.placements_in(quadrant)
    }
    assert translated == set(reference_grid.placements)
    with builder.build(time_limit_s=2) as model, BeasleyModelBuilder(
        reference_grid, full_pallet,
    ).build(time_limit_s=2) as full_model:
        result = model.solve()
        reference = full_model.solve()
    assert_unit_solution(result, 3, grid, quadrant)
    assert_unit_solution(reference, 3, reference_grid, full_pallet)
    with AndradeBirgin2013ModelBuilder(width, height, 2, 1).build(2) as existing:
        existing.solve()
        assert existing.solution.get_status() == 101
        assert existing.solution.get_objective_value() == result.objective_value


def test_fractional_quadrant_uses_global_grid_and_known_area_bound():
    grid, quadrant, builder = make_builder((61, 51, 6, 4))
    with builder.build(time_limit_s=2) as model:
        assert len(model.placements) == 17
        assert quadrant.x_min == Fraction(244, 5)
        assert quadrant.y_min == Fraction(204, 5)
        assert all(p.x >= 50 and p.y >= 42 for p in model.placements)
        # Global normal coordinates are even. All rectangles lie inside the
        # effective 10x8 region [50,60) x [42,50); floor(80/24) = 3.
        result = model.solve()
    assert_unit_solution(result, 3, grid, quadrant)


def test_open_upper_frontiers_keep_edge_touching_placements_and_exclude_protrusions():
    grid, quadrant, builder = make_builder((11, 11, 2, 1), 1, Fraction(1, 2))
    # Q1 ends at 7.5. Corners (6,0) and (0,7) are global candidates but protrude.
    with builder.build(time_limit_s=2) as model:
        assert grid.contains_placement(Placement(6, 0, 2, 1))
        assert Placement(6, 0, 2, 1) not in model.placements
        assert grid.contains_placement(Placement(0, 7, 2, 1))
        assert Placement(0, 7, 2, 1) not in model.placements
        assert Placement(5, 0, 2, 1) in model.placements
        result = model.solve()
    # All corners are integral, hence the usable region is 7x7: floor(49/2).
    assert_unit_solution(result, 24, grid, quadrant)


def test_applicable_but_empty_quadrant_has_a_proven_zero_optimum():
    grid, quadrant, builder = make_builder((16, 16, 3, 3))
    with builder.build(time_limit_s=2) as model:
        assert model.placements == ()
        assert model.cplex_model.variables.get_num() == 0
        assert model.cplex_model.linear_constraints.get_num() == 0
        result = model.solve()
    assert_unit_solution(result, 0, grid, quadrant)


def test_binary_model_rows_are_the_phase_a_normal_point_incidences():
    grid, quadrant, builder = make_builder((16, 16, 6, 4), alpha=Fraction(1, 2))
    with builder.build(time_limit_s=2) as model:
        assert all(t == "B" for t in model.cplex_model.variables.get_types())
        assert model.cplex_model.variables.get_lower_bounds() == [0.0] * len(model.placements)
        assert model.cplex_model.variables.get_upper_bounds() == [1.0] * len(model.placements)
        assert model.cplex_model.objective.get_linear() == [1.0] * len(model.placements)
        assert model.cplex_model.parameters.timelimit.get() == 2
        coverage = [grid.covered_points(p) for p in model.placements]
        assert set(model.coverage_rows) == set().union(*coverage)
        for point, indices in model.coverage_rows.items():
            assert indices == tuple(i for i, points in enumerate(coverage) if point in points)
            name = f"cover_{point[0]}_{point[1]}"
            row = model.cplex_model.linear_constraints.get_rows(name)
            assert row.ind == list(indices)
            assert row.val == [1.0] * len(indices)
            assert model.cplex_model.linear_constraints.get_senses(name) == "L"
            assert model.cplex_model.linear_constraints.get_rhs(name) == 1
        for (i, a), (j, b) in combinations(enumerate(model.placements), 2):
            assert bool(coverage[i] & coverage[j]) == (not disjoint(a, b))


def test_generic_objective_coefficients_do_not_change_the_feasible_set():
    _, _, builder = make_builder((11, 11, 2, 1))
    with builder.build(time_limit_s=2) as unit, builder.build(
        time_limit_s=2, objective=lambda placement: 3.0 if placement.rotated else 1.0,
    ) as weighted:
        assert weighted.placements == unit.placements
        assert weighted.coverage_rows == unit.coverage_rows
        result = weighted.solve()
    assert result.proven_optimal
    assert result.objective_value == result.best_bound == 6
    assert len(result.placements) == 2
    assert all(p.rotated for p in result.placements)


@pytest.mark.parametrize("limit", [0, -1, True, None, float("inf"), float("nan")])
def test_invalid_time_limit_is_rejected_before_cplex_construction(limit):
    _, _, builder = make_builder((11, 11, 2, 1))
    with pytest.raises(ValueError, match="time_limit_s"):
        builder.build(time_limit_s=limit)


@pytest.mark.parametrize("coefficient", [True, None, float("nan"), float("inf"), cplex.infinity])
def test_invalid_objective_coefficient_is_rejected(coefficient):
    _, _, builder = make_builder((11, 11, 2, 1))
    with pytest.raises(ValueError, match="coefficients"):
        builder.build(objective=lambda placement: coefficient)


def stub_model(raw_status, feasible, bound=2):
    solution = SimpleNamespace(
        get_status=Mock(return_value=raw_status),
        is_primal_feasible=Mock(return_value=feasible),
        get_objective_value=Mock(return_value=1.0),
        get_values=Mock(return_value=[1.0]),
        MIP=SimpleNamespace(get_best_objective=Mock(return_value=bound)),
    )
    cplex_model = SimpleNamespace(solve=Mock(), solution=solution, end=Mock())
    return BeasleyModel(
        cplex_model, (Placement(9, 9, 2, 1),), ("x_9_9",), (1.0,), {},
    )


@pytest.mark.parametrize("raw, feasible, expected_status, termination, optimal, incumbent, bound", [
    (101, True, PAVER.MODEL_STATUS_OPTIMAL, PAVER.TERMINATION_NORMAL, True, 1, 1),
    (102, True, PAVER.MODEL_STATUS_FEASIBLE, PAVER.TERMINATION_NORMAL, False, 1, 2),
    (107, True, PAVER.MODEL_STATUS_FEASIBLE, PAVER.TERMINATION_TIME_LIMIT, False, 1, 2),
    (108, False, PAVER.MODEL_STATUS_NO_SOLUTION, PAVER.TERMINATION_TIME_LIMIT, False, None, 2),
    (103, False, PAVER.MODEL_STATUS_NO_SOLUTION_RETURNED, PAVER.TERMINATION_NORMAL, False, None, None),
    (115, True, PAVER.MODEL_STATUS_INTERMEDIATE_INFEASIBLE, PAVER.TERMINATION_NORMAL, False, None, None),
    (999, True, PAVER.MODEL_STATUS_ERROR, PAVER.TERMINATION_ERROR, False, None, None),
])
def test_result_preserves_solver_status_incumbent_and_bound(
    raw, feasible, expected_status, termination, optimal, incumbent, bound,
):
    with stub_model(raw, feasible, bound=1 if optimal else 2) as model:
        result = model.solve()
        assert result.status.model_status == expected_status
        assert result.status.termination_status == termination
        assert result.proven_optimal is optimal
        assert result.objective_value == incumbent
        assert result.best_bound == bound
        assert result.raw_cplex_status == raw
        assert len(result.placements) == (1 if incumbent is not None else 0)
        if incumbent is None:
            model.cplex_model.solution.get_objective_value.assert_not_called()
            model.cplex_model.solution.get_values.assert_not_called()


@pytest.mark.parametrize("bound", [float("inf"), float("nan"), cplex.infinity, None])
def test_unavailable_bound_does_not_discard_a_timeout_incumbent(bound):
    with stub_model(107, True, bound) as model:
        result = model.solve()
    assert result.objective_value == 1
    assert result.status.termination_status == PAVER.TERMINATION_TIME_LIMIT
    assert not result.proven_optimal
    assert result.best_bound is None


def test_bound_query_error_does_not_discard_a_feasible_incumbent():
    with stub_model(107, True) as model:
        model.cplex_model.solution.MIP.get_best_objective.side_effect = (
            cplex.exceptions.CplexSolverError("bound unavailable")
        )
        result = model.solve()
    assert result.error_message is None
    assert result.objective_value == 1
    assert result.best_bound is None


def test_solver_error_is_explicit_and_context_releases_resources():
    model = stub_model(101, True)
    with model:
        model.cplex_model.solve.side_effect = cplex.exceptions.CplexSolverError("solve failed")
        result = model.solve()
    assert result.status.termination_status == PAVER.TERMINATION_ERROR
    assert not result.proven_optimal
    assert result.objective_value is None
    assert result.placements == ()
    assert "solve failed" in result.error_message
    model.close()
    model.cplex_model.end.assert_called_once()
    with pytest.raises(RuntimeError, match="closed"):
        model.solve()
