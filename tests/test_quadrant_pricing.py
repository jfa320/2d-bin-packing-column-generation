"""Isolated pricing, configuration-cost identities and limit certificates."""

from contextlib import nullcontext
from fractions import Fraction
from itertools import combinations
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

cplex = pytest.importorskip("cplex")

from models.quadrant_column_generation import (
    Placement, build_quadrants, generate_global_discretization,
)
from models.quadrant_column_generation.beasley_model import BeasleyModelBuilder, BeasleyResult
from models.quadrant_column_generation.master_problem import RestrictedMasterBuilder
from models.quadrant_column_generation.pricing_problem import QuadrantPricing
from models.quadrant_column_generation import pricing_problem as module
from utils.paver_constants import PaverConstants as PAVER
from utils.status_normalizer import map_cplex_mip_status


@pytest.fixture
def geometry():
    grid = generate_global_discretization(11, 11, 2, 1)
    quadrants = build_quadrants(11, 11, 2, 1).quadrants
    return grid, quadrants


def manual_objective(grid, placements, pi):
    # Independently reconstruct P(s) from rectangle geometry and I x J.
    points = {
        (i, j) for i in grid.I for j in grid.J
        if any(p.x <= i < p.x + p.width and p.y <= j < p.y + p.height for p in placements)
    }
    return len(placements) - sum(pi.get(point, 0.0) for point in points)


def disjoint(a, b):
    return (a.x + a.width <= b.x or b.x + b.width <= a.x
            or a.y + a.height <= b.y or b.y + b.height <= a.y)


@pytest.mark.parametrize("dimensions, quadrant_index", [
    ((11, 11, 2, 1), 4), ((16, 11, 2, 1), 4),
    ((6, 6, 1, 1), 1), ((16, 16, 3, 3), 4),
])
def test_zero_pi_matches_unit_beasley(dimensions, quadrant_index):
    grid = generate_global_discretization(*dimensions)
    quadrant = build_quadrants(*dimensions).quadrants[quadrant_index - 1]
    with BeasleyModelBuilder(grid, quadrant).build(time_limit_s=2) as model:
        unit = model.solve()
    result = QuadrantPricing(grid, quadrant).solve(0.4, {}, time_limit_s=2)

    assert result.proven_optimal
    assert result.pricing_objective == unit.objective_value
    assert result.best_bound == unit.best_bound
    assert result.reduced_cost == pytest.approx(unit.objective_value - 0.4)
    assert result.reduced_cost_upper_bound == pytest.approx(unit.best_bound - 0.4)
    assert result.configuration.item_count == len(unit.placements)
    assert result.configuration.quadrant == quadrant
    assert result.total_time_s >= result.solve_time_s >= 0


def test_complete_numerical_example_and_manual_reduced_cost(geometry):
    grid, quadrants = geometry
    pi, sigma = {(9, 9): 0.25, (10, 9): 0.5}, 0.5
    result = QuadrantPricing(grid, quadrants[3]).solve(sigma, pi, time_limit_s=2)

    manual = manual_objective(grid, result.configuration.placements, pi) - sigma
    assert result.error_message is None
    assert result.configuration.item_count == 2
    assert result.pricing_objective == pytest.approx(1.25)
    assert result.reduced_cost == pytest.approx(manual)
    assert manual == pytest.approx(0.75)
    assert result.best_bound == pytest.approx(1.25)
    assert result.reduced_cost_upper_bound == pytest.approx(0.75)
    assert result.raw_cplex_status == 101
    assert result.status.termination_status == PAVER.TERMINATION_NORMAL
    assert result.proven_optimal
    assert result.has_improving_column
    assert not result.closure_proven
    print("NUMERICAL EXAMPLE", {
        "sigma": sigma, "pi": pi,
        "placements": result.configuration.placements,
        "pricing_objective": result.pricing_objective,
        "manual_rc": manual, "reported_rc": result.reduced_cost,
        "best_bound": result.best_bound, "rc_upper_bound": result.reduced_cost_upper_bound,
        "raw_cplex_status": result.raw_cplex_status, "status": result.status,
    })


def test_placement_coefficients_exclude_sigma_and_use_all_covered_points(geometry, monkeypatch):
    grid, quadrants = geometry
    pi = {(9, 9): 0.25, (10, 9): 0.5}
    coefficients = []
    original = BeasleyModelBuilder.build

    def record(builder, **kwargs):
        assert builder.discretization is grid
        model = original(builder, **kwargs)
        coefficients.append(model.objective_coefficients)
        return model

    monkeypatch.setattr(BeasleyModelBuilder, "build", record)
    pricing = QuadrantPricing(grid, quadrants[3])
    first = pricing.solve(0, pi, time_limit_s=2)
    second = pricing.solve(10, pi, time_limit_s=2)

    assert coefficients == [(0.25, 1.0, 0.75, 0.5)] * 2
    assert first.pricing_objective == second.pricing_objective
    assert first.best_bound == second.best_bound
    assert first.reduced_cost - second.reduced_cost == pytest.approx(10)
    assert first.reduced_cost_upper_bound - second.reduced_cost_upper_bound == pytest.approx(10)


def test_configuration_coverage_matches_the_master_column(geometry):
    grid, quadrants = geometry
    pi = {(9, 9): 0.25, (10, 9): 0.5}
    result = QuadrantPricing(grid, quadrants[3]).solve(0.5, pi, time_limit_s=2)
    with RestrictedMasterBuilder(grid, quadrants).build([result.configuration], time_limit_s=2) as master:
        column = master.cplex_model.variables.get_cols(master.variable_names[0])
        names = master.cplex_model.linear_constraints.get_names()
        incidence = {names[i] for i in column.ind}
        expected_points = set().union(*(
            grid.covered_points(p) for p in result.configuration.placements
        ))
        assert incidence == {"quadrant_4"} | {f"cover_{i}_{j}" for i, j in expected_points}
        assert all(value == 1 for value in column.val)
        assert result.reduced_cost == pytest.approx(
            result.configuration.item_count - sum(pi.get(p, 0) for p in expected_points) - 0.5,
        )


@pytest.mark.parametrize("dimensions, alpha, pi, sigma", [
    ((11, 11, 2, 1), 0.8, {(9, 9): 0.25, (10, 9): 0.5}, 0.5),
    ((16, 11, 2, 1), 0.8, {(13, 9): 0.7, (14, 10): 0.2}, 1.0),
    ((16, 16, 6, 4), Fraction(1, 2), {(8, 8): 0.25, (10, 8): 0.5, (12, 12): 0.1}, 0.3),
])
def test_pricing_matches_exhaustive_configuration_objectives(dimensions, alpha, pi, sigma):
    grid = generate_global_discretization(*dimensions)
    quadrant = build_quadrants(*dimensions, alpha=alpha).quadrants[3]
    placements = grid.placements_in(quadrant)
    assert len(placements) <= 12
    best = 0.0  # The empty configuration is feasible.
    for mask in range(1 << len(placements)):
        selected = tuple(p for index, p in enumerate(placements) if mask & (1 << index))
        if all(disjoint(a, b) for a, b in combinations(selected, 2)):
            best = max(best, manual_objective(grid, selected, pi))
    result = QuadrantPricing(grid, quadrant).solve(sigma, pi, time_limit_s=2)
    assert result.proven_optimal
    assert result.pricing_objective == pytest.approx(best)
    assert result.reduced_cost == pytest.approx(best - sigma)
    assert result.best_bound == pytest.approx(best)
    assert result.reduced_cost_upper_bound == pytest.approx(best - sigma)


def test_optimal_nonpositive_reduced_cost_certifies_the_quadrant(geometry):
    grid, quadrants = geometry
    result = QuadrantPricing(grid, quadrants[3]).solve(2, {}, time_limit_s=2)
    assert result.proven_optimal
    assert result.reduced_cost == 0
    assert result.reduced_cost_upper_bound == 0
    assert result.closure_proven
    assert result.closure_basis == "optimal_pricing"
    assert not result.has_improving_column


def test_negative_placement_coefficients_allow_the_empty_configuration(geometry):
    grid, quadrants = geometry
    pi = {(i, j): 1 for i in grid.I for j in grid.J}
    result = QuadrantPricing(grid, quadrants[3]).solve(0.5, pi, time_limit_s=2)
    assert result.configuration.placements == ()
    assert result.pricing_objective == 0
    assert result.reduced_cost == -0.5
    assert result.best_bound == 0
    assert result.reduced_cost_upper_bound == -0.5
    assert result.closure_proven


def test_input_prices_are_not_negated_or_clipped(geometry):
    grid, quadrants = geometry
    result = QuadrantPricing(grid, quadrants[3]).solve(-0.5, {(9, 9): -0.25}, time_limit_s=2)
    assert result.pricing_objective == pytest.approx(2.25)
    assert result.reduced_cost == pytest.approx(2.75)


def inject_beasley(monkeypatch, *, raw=107, feasible=True, objective=1.0,
                   bound=3.0, placements=None, error=None):
    if placements is None:
        placements = (Placement(9, 9, 2, 1),) if feasible else ()
    state = map_cplex_mip_status(raw, has_feasible_solution=feasible)
    base = BeasleyResult(objective, placements, state, raw == 101 and feasible,
                         bound, 0.125, raw_cplex_status=raw, error_message=error)
    built = Mock(return_value=nullcontext(SimpleNamespace(solve=Mock(return_value=base))))
    monkeypatch.setattr(module.BeasleyModelBuilder, "build", built)
    return built


def test_timeout_nonpositive_incumbent_and_positive_reduced_bound_is_inconclusive(geometry, monkeypatch):
    grid, quadrants = geometry
    inject_beasley(monkeypatch, objective=1, bound=3)
    result = QuadrantPricing(grid, quadrants[3]).solve(2, {})
    assert result.configuration is not None
    assert result.reduced_cost == -1
    assert result.best_bound == 3
    assert result.reduced_cost_upper_bound == 1
    assert not result.proven_optimal
    assert not result.closure_proven
    assert result.status.termination_status == PAVER.TERMINATION_TIME_LIMIT


def test_timeout_positive_incumbent_returns_a_feasible_improving_column(geometry, monkeypatch):
    grid, quadrants = geometry
    inject_beasley(monkeypatch)
    result = QuadrantPricing(grid, quadrants[3]).solve(0.5, {})
    assert result.configuration.item_count == 1
    assert result.reduced_cost == 0.5
    assert result.has_improving_column
    assert result.reduced_cost_upper_bound == 2.5
    assert result.status.termination_status == PAVER.TERMINATION_TIME_LIMIT
    assert not result.proven_optimal
    assert not result.closure_proven


@pytest.mark.parametrize("feasible", [True, False])
def test_timeout_bound_can_certify_closure_after_subtracting_sigma(geometry, monkeypatch, feasible):
    grid, quadrants = geometry
    inject_beasley(monkeypatch, raw=107 if feasible else 108, feasible=feasible,
                   objective=1 if feasible else None, bound=3)
    result = QuadrantPricing(grid, quadrants[3]).solve(3.5, {})
    assert result.best_bound == 3  # Positive Beasley bound is not the reduced bound.
    assert result.reduced_cost_upper_bound == -0.5
    assert result.closure_proven
    assert result.closure_basis == "pricing_upper_bound"
    assert not result.proven_optimal
    assert (result.configuration is not None) is feasible


def test_timeout_without_bound_cannot_certify_closure(geometry, monkeypatch):
    grid, quadrants = geometry
    inject_beasley(monkeypatch, bound=None)
    result = QuadrantPricing(grid, quadrants[3]).solve(2, {})
    assert result.reduced_cost == -1
    assert result.reduced_cost_upper_bound is None
    assert not result.closure_proven


def test_optimal_incumbent_supplies_a_bound_when_mip_bound_is_missing(geometry, monkeypatch):
    grid, quadrants = geometry
    inject_beasley(monkeypatch, raw=101, objective=2, bound=None,
                   placements=(Placement(9, 9, 2, 1), Placement(9, 10, 2, 1)))
    result = QuadrantPricing(grid, quadrants[3]).solve(2, {})
    assert result.proven_optimal
    assert result.best_bound is None
    assert result.reduced_cost_upper_bound == 0
    assert result.closure_proven
    assert result.closure_basis == "optimal_pricing"


@pytest.mark.parametrize("raw", [103, 110, 115, 118, 119, 999])
def test_invalid_solver_states_cannot_certify_closure(geometry, monkeypatch, raw):
    grid, quadrants = geometry
    inject_beasley(monkeypatch, raw=raw, feasible=False, objective=None, bound=0)
    result = QuadrantPricing(grid, quadrants[3]).solve(1, {})
    assert result.configuration is None
    assert result.reduced_cost_upper_bound is None
    assert not result.closure_proven


def test_error_telemetry_cannot_supply_a_bound_certificate(geometry, monkeypatch):
    grid, quadrants = geometry
    inject_beasley(monkeypatch, bound=1, error="postprocessing error")
    result = QuadrantPricing(grid, quadrants[3]).solve(2, {})
    assert result.error_message == "postprocessing error"
    assert result.reduced_cost_upper_bound is None
    assert not result.closure_proven


@pytest.mark.parametrize("objective, bound", [(2, 3), (1, 0.5)])
def test_inconsistent_objective_or_bound_is_an_explicit_error(geometry, monkeypatch, objective, bound):
    grid, quadrants = geometry
    inject_beasley(monkeypatch, objective=objective, bound=bound)
    result = QuadrantPricing(grid, quadrants[3]).solve(2, {})
    assert result.configuration is None
    assert result.error_message
    assert result.status.termination_status == PAVER.TERMINATION_ERROR
    assert not result.closure_proven


@pytest.mark.parametrize("sigma", [None, True, float("inf"), float("nan"), cplex.infinity])
def test_invalid_sigma_is_rejected(geometry, sigma):
    grid, quadrants = geometry
    with pytest.raises(ValueError, match="sigma"):
        QuadrantPricing(grid, quadrants[3]).solve(sigma, {})


@pytest.mark.parametrize("point", [(-1, 0), (12, 0), (0, 12), (True, 9), ("9", 9), "bad"])
def test_invalid_pi_point_is_not_silently_ignored(geometry, point):
    grid, quadrants = geometry
    with pytest.raises(ValueError, match="global normal-point grid"):
        QuadrantPricing(grid, quadrants[3]).solve(0, {point: 0.1})


@pytest.mark.parametrize("value", [None, True, float("inf"), float("nan")])
def test_invalid_pi_value_is_rejected(geometry, value):
    grid, quadrants = geometry
    with pytest.raises(ValueError, match="finite real number"):
        QuadrantPricing(grid, quadrants[3]).solve(0, {(9, 9): value})


@pytest.mark.parametrize("kwargs", [
    {"time_limit_s": 0}, {"time_limit_s": float("inf")},
    {"reduced_cost_tolerance": -1}, {"reduced_cost_tolerance": True},
])
def test_invalid_limits_or_tolerance_are_rejected(geometry, kwargs):
    grid, quadrants = geometry
    with pytest.raises(ValueError):
        QuadrantPricing(grid, quadrants[3]).solve(0, {}, **kwargs)
