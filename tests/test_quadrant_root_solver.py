"""Root CG protocol tests plus comparisons against fully enumerated masters."""

from dataclasses import replace
from itertools import combinations
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock

import pytest

cplex = pytest.importorskip("cplex")

from models.quadrant_column_generation import (
    QuadrantConfiguration, build_quadrants, generate_global_discretization,
)
from models.quadrant_column_generation.master_problem import (
    MasterDualPrices, RestrictedMasterBuilder, RestrictedMasterResult,
)
from models.quadrant_column_generation.pricing_problem import PricingResult
from models.quadrant_column_generation import pricing_problem
from models.quadrant_column_generation.beasley_model import BeasleyResult
from models.quadrant_column_generation.root_solver import CGStatus, EPS, solve_root
from models.quadrant_column_generation import root_solver as module
from utils.paver_constants import PaverConstants as PAVER
from utils.status_normalizer import map_cplex_lp_status, map_cplex_mip_status


@pytest.fixture
def geometry():
    grid = generate_global_discretization(3, 4, 1, 1)
    quadrants = build_quadrants(3, 4, 1, 1, alpha=0.5).quadrants
    return grid, quadrants


def candidate(grid, quadrant):
    return QuadrantConfiguration(quadrant, (grid.placements_in(quadrant)[0],))


def price(quadrant, sigma, config=None, *, bound=None, raw=101, feasible=True):
    config = QuadrantConfiguration(quadrant) if config is None else config
    objective = float(config.item_count) if feasible else None
    rc = objective - sigma if feasible else None
    bound = float(config.item_count) if bound is None else bound
    upper = bound - sigma
    closed = upper <= EPS and (rc is None or rc <= EPS)
    return PricingResult(
        config if feasible else None, objective, rc,
        map_cplex_mip_status(raw, has_feasible_solution=feasible), raw == 101 and feasible,
        bound, upper, 0.01, 0.02, sigma, EPS,
        has_improving_column=rc is not None and rc > EPS,
        closure_proven=closed,
        closure_basis=("optimal_pricing" if raw == 101 else "pricing_upper_bound") if closed else None,
        raw_cplex_status=raw,
    )


@pytest.fixture
def protocol(monkeypatch, geometry):
    """Scripted solvers test orchestration; real LP/MIPs are tested below."""
    grid, quadrants = geometry
    clock = [0.0]
    events, calls, budgets = [], [], []
    rmp_values, sigma_values = [0.0], [{k: 0.0 for k in range(1, 5)}]
    plan = {}
    costs = {"build": 0.2, "rmp": 0.1, "pricing": 0.1, "add": 0.02, "close": 0.0}
    masters = []
    monkeypatch.setattr(module, "perf_counter", lambda: clock[0])

    class FakeMaster:
        def __init__(self, configs):
            self.configurations = list(configs)
            self.model_revision = len(configs)
            self.solves = 0
            self.close = Mock(side_effect=self._close)
            self.cplex_model = SimpleNamespace(parameters=SimpleNamespace(
                timelimit=SimpleNamespace(set=lambda budget: budgets.append(("rmp", budget, clock[0]))),
            ))

        def _close(self):
            clock[0] += costs["close"]

        def solve(self):
            self.solves += 1
            index = min(self.solves - 1, len(rmp_values) - 1)
            sigma = sigma_values[min(self.solves - 1, len(sigma_values) - 1)]
            events.append(("rmp", self.model_revision))
            clock[0] += costs["rmp"]
            pi = {(i, j): 0.0 for i in grid.I for j in grid.J}
            return RestrictedMasterResult(
                rmp_values[index], {}, map_cplex_lp_status(1, True), True,
                MasterDualPrices(dict(sigma), pi, self.model_revision), 0.01, self.model_revision,
                raw_cplex_status=1,
            )

        def add_configuration(self, config):
            events.append(("add", config.quadrant.index))
            self.configurations.append(config)
            self.model_revision += 1
            clock[0] += costs["add"]

    class FakeBuilder:
        def __init__(self, discretization, qs):
            self.quadrants = tuple(qs)

        def build(self, configs, *, time_limit_s):
            budgets.append(("build", time_limit_s, clock[0]))
            clock[0] += costs["build"]
            master = FakeMaster(configs)
            masters.append(master)
            return master

    class FakePricing:
        def __init__(self, discretization, quadrant, remaining):
            self.quadrant = quadrant

        def solve(self, sigma, pi, *, time_limit_s, reduced_cost_tolerance):
            master = masters[-1]
            calls.append((master.solves, self.quadrant.index, master.model_revision, sigma, pi))
            budgets.append(("pricing", time_limit_s, clock[0]))
            events.append(("pricing", self.quadrant.index, master.model_revision))
            assert reduced_cost_tolerance == EPS
            clock[0] += costs["pricing"]
            action = plan.get((master.solves, self.quadrant.index))
            if action is None:
                return price(self.quadrant, sigma)
            return action(self.quadrant, sigma, pi)

    monkeypatch.setattr(module, "RestrictedMasterBuilder", FakeBuilder)
    monkeypatch.setattr(module, "_DeadlinePricing", FakePricing)
    return SimpleNamespace(grid=grid, quadrants=quadrants, clock=clock, events=events,
                           calls=calls, budgets=budgets, rmp_values=rmp_values,
                           sigma_values=sigma_values, plan=plan, costs=costs, masters=masters)


def add_once(protocol, k=1, *, timeout=False):
    p = protocol
    p.rmp_values[:] = [0.0, 1.0]
    p.sigma_values[:] = [{i: 0.0 for i in range(1, 5)}, {i: float(i == k) for i in range(1, 5)}]
    p.plan[(1, k)] = lambda q, s, pi: price(
        q, s, candidate(p.grid, q), raw=107 if timeout else 101, bound=2 if timeout else 1,
    )


def test_immediate_convergence_starts_with_four_empty_configurations(protocol):
    p = protocol
    result = solve_root(p.grid, p.quadrants, time_limit_s=10)
    assert result.status == CGStatus.CONVERGED
    assert result.objective_value == 0
    assert result.lp_is_current
    assert len(result.iterations) == 1
    assert [c.quadrant.index for c in result.configurations] == [1, 2, 3, 4]
    assert all(not c.placements for c in result.configurations)
    assert not result.iterations[0].columns_added
    assert [call[1] for call in p.calls] == [1, 2, 3, 4]
    p.masters[0].close.assert_called_once()


def test_add_column_then_reoptimize_and_converge_with_fresh_duals(protocol):
    p = protocol
    add_once(p)
    result = solve_root(p.grid, p.quadrants, time_limit_s=10)
    assert result.converged
    assert result.objective_value == 1
    assert [row.rmp.objective_value for row in result.iterations] == [0, 1]
    assert [len(row.columns_added) for row in result.iterations] == [1, 0]
    assert result.iterations[0].outcome == "COLUMNS_ADDED"
    assert result.iterations[0].master_revision == 4
    assert result.iterations[1].master_revision == 5
    assert p.events[:6] == [("rmp", 4), ("pricing", 1, 4), ("pricing", 2, 4),
                            ("pricing", 3, 4), ("pricing", 4, 4), ("add", 1)]
    assert all(call[4] is p.calls[0][4] for call in p.calls[:4])
    assert p.calls[4][4] is not p.calls[0][4]
    with pytest.raises(TypeError):
        p.calls[0][4][(0, 0)] = 100  # Every pricing receives a read-only snapshot.
    assert result.iterations[0].sigma[1] == 0
    assert result.iterations[1].sigma[1] == 1


def test_multiple_quadrants_can_add_columns_in_one_batch(protocol):
    p = protocol
    p.rmp_values[:] = [0, 2]
    for k in (1, 3):
        p.plan[(1, k)] = lambda q, s, pi: price(q, s, candidate(p.grid, q))
    result = solve_root(p.grid, p.quadrants, time_limit_s=10)
    assert result.converged
    assert len(result.iterations[0].columns_found) == 2
    assert len(result.iterations[0].columns_added) == 2
    assert result.master_revision == 6
    assert p.events.index(("add", 1)) > p.events.index(("pricing", 4, 4))


def test_column_identity_includes_the_quadrant(protocol):
    p = protocol
    shared = next(placement for placement in p.grid.placements
                  if placement.x == 0 and placement.y == 2)
    for k in (1, 2):
        p.plan[(1, k)] = lambda q, s, pi: price(q, s, QuadrantConfiguration(q, (shared,)))
    result = solve_root(p.grid, p.quadrants, time_limit_s=10)
    first = result.iterations[0]
    assert len(first.columns_added) == 2
    assert first.columns_added[0].placements == first.columns_added[1].placements
    assert first.columns_added[0] != first.columns_added[1]
    assert not first.duplicates


def test_duplicate_positive_column_stops_inconclusively_without_an_infinite_loop(protocol):
    p = protocol
    add_once(p)
    p.sigma_values[:] = [{k: 0.0 for k in range(1, 5)}]
    p.plan[(2, 1)] = p.plan[(1, 1)]
    result = solve_root(p.grid, p.quadrants, time_limit_s=10)
    assert result.status == CGStatus.INCONCLUSIVE
    assert result.stop_reason == "duplicate_improving_columns"
    assert len(result.configurations) == 5
    assert len(result.iterations[-1].columns_found) == 1
    assert len(result.iterations[-1].duplicates) == 1
    assert not result.iterations[-1].columns_added


def test_timeout_with_an_improving_column_can_continue_and_converge(protocol):
    p = protocol
    add_once(p, timeout=True)
    result = solve_root(p.grid, p.quadrants, time_limit_s=10)
    assert result.converged
    assert result.had_timeouts
    record = result.iterations[0].pricings[0]
    assert record.added
    assert record.result.status.termination_status == PAVER.TERMINATION_TIME_LIMIT
    assert not record.result.proven_optimal
    assert result.iterations[1].rmp.objective_value == 1


def test_timeout_without_improvement_and_with_positive_bound_is_inconclusive(protocol):
    p = protocol
    p.plan[(1, 2)] = lambda q, s, pi: price(q, s, raw=107, bound=1)
    result = solve_root(p.grid, p.quadrants, time_limit_s=10)
    assert result.status == CGStatus.INCONCLUSIVE
    assert result.stop_reason == "pricing_inconclusive"
    assert result.had_timeouts
    assert len(result.iterations[0].pricings) == 4
    assert result.iterations[0].pricings[1].result.reduced_cost == 0
    assert result.iterations[0].pricings[1].result.reduced_cost_upper_bound == 1


def test_four_valid_bound_certificates_close_even_without_optimal_pricing(protocol):
    p = protocol
    for k in range(1, 5):
        p.plan[(1, k)] = lambda q, s, pi: price(q, s, raw=108, feasible=False, bound=0)
    result = solve_root(p.grid, p.quadrants, time_limit_s=10)
    assert result.converged
    assert result.had_timeouts
    assert all(not rec.result.proven_optimal for rec in result.iterations[0].pricings)


def test_old_certificates_cannot_close_the_next_iteration(protocol):
    p = protocol
    add_once(p, k=2)
    p.plan[(2, 1)] = lambda q, s, pi: price(q, s, raw=107, bound=1)
    result = solve_root(p.grid, p.quadrants, time_limit_s=10)
    assert not result.converged
    assert result.iterations[0].pricings[0].result.closure_proven
    assert not result.iterations[1].pricings[0].result.closure_proven
    assert result.iterations[1].pricings[0].master_revision == 5
    assert len(p.calls) == 8


def test_every_resolution_receives_the_current_remaining_budget(protocol):
    p = protocol
    add_once(p)
    solve_root(p.grid, p.quadrants, time_limit_s=10)
    for phase, budget, called_at in p.budgets:
        assert budget == pytest.approx(10 - called_at)
    assert p.budgets[1][0] == "rmp"
    assert p.budgets[1][1] == pytest.approx(9.8)  # Construction consumed 0.2.
    limits = [budget for phase, budget, _ in p.budgets if phase != "build"]
    assert all(a > b for a, b in zip(limits, limits[1:]))


def test_deadline_prevents_unstarted_pricings_and_late_convergence(protocol):
    p = protocol
    result = solve_root(p.grid, p.quadrants, time_limit_s=0.45)
    assert not result.converged
    assert result.stop_reason == "global_deadline"
    assert len(p.calls) == 2
    assert len(result.iterations[0].pricings) == 2
    assert result.had_timeouts


def test_zero_budget_never_constructs_or_solves_a_master(protocol):
    p = protocol
    result = solve_root(p.grid, p.quadrants, time_limit_s=0)
    assert result.stop_reason == "global_deadline"
    assert result.objective_value is None
    assert not result.lp_is_current
    assert not p.masters
    assert not p.calls


def test_global_deadline_includes_resource_cleanup(protocol):
    p = protocol
    p.costs["close"] = 0.2
    result = solve_root(p.grid, p.quadrants, time_limit_s=0.8)
    assert result.status == CGStatus.INCONCLUSIVE
    assert result.stop_reason == "global_deadline"
    assert result.had_timeouts
    assert result.iterations[0].outcome == "CG_INCONCLUSIVE"


def test_deadline_in_construction_stops_before_master_solve(protocol):
    p = protocol
    result = solve_root(p.grid, p.quadrants, time_limit_s=0.1)
    assert result.stop_reason == "global_deadline"
    assert p.masters[0].solves == 0
    assert not p.calls
    p.masters[0].close.assert_called_once()


def test_pricing_native_solve_receives_budget_after_model_construction(geometry, monkeypatch):
    grid, quadrants = geometry
    clock = [0.0]
    built = MagicMock()
    built.__enter__.return_value = built
    built.solve.return_value = BeasleyResult(
        0.0, (), map_cplex_mip_status(101, True), True, 0.0, 0.01, raw_cplex_status=101,
    )

    def construct(builder, **kwargs):
        assert kwargs["time_limit_s"] == 1.0
        clock[0] += 0.3
        return built

    monkeypatch.setattr(pricing_problem.BeasleyModelBuilder, "build", construct)
    pricer = module._DeadlinePricing(grid, quadrants[0], lambda: 1.0 - clock[0])
    pricer.solve(0, {}, time_limit_s=1.0)
    built.cplex_model.parameters.timelimit.set.assert_called_once_with(0.7)
    built.solve.assert_called_once()


def test_pricing_construction_exhausting_budget_never_calls_native_solve(geometry, monkeypatch):
    grid, quadrants = geometry
    clock = [0.0]
    built = MagicMock()

    def construct(builder, **kwargs):
        clock[0] += 0.3
        return built

    monkeypatch.setattr(pricing_problem.BeasleyModelBuilder, "build", construct)
    pricer = module._DeadlinePricing(grid, quadrants[0], lambda: 0.2 - clock[0])
    with pytest.raises(module._DeadlineExpired, match="construction"):
        pricer.solve(0, {}, time_limit_s=0.2)
    built.solve.assert_not_called()
    built.close.assert_called_once()


def test_deadline_after_adding_columns_marks_the_last_lp_as_outdated(protocol):
    p = protocol
    add_once(p)
    result = solve_root(p.grid, p.quadrants, time_limit_s=0.715)
    assert result.stop_reason == "global_deadline"
    assert len(result.iterations[0].columns_added) == 1
    assert result.objective_value == 0
    assert result.master_revision == 5
    assert result.last_rmp.model_revision == 4
    assert not result.lp_is_current


def test_decreasing_rmp_objective_is_detected(protocol):
    p = protocol
    add_once(p)
    p.rmp_values[:] = [0, -1]
    result = solve_root(p.grid, p.quadrants, time_limit_s=10)
    assert not result.converged
    assert result.stop_reason == "rmp_objective_decreased"
    assert len(p.calls) == 4


@pytest.mark.parametrize("field, wrong", [("sigma", 100), ("reduced_cost_tolerance", EPS / 2)])
def test_mismatched_pricing_snapshot_or_tolerance_cannot_close(protocol, field, wrong):
    p = protocol
    p.plan[(1, 1)] = lambda q, s, pi: replace(price(q, s), **{field: wrong})
    result = solve_root(p.grid, p.quadrants, time_limit_s=10)
    assert not result.converged
    assert result.iterations[0].pricings[0].error_message


def test_a_closure_flag_without_an_upper_bound_is_insufficient(protocol):
    p = protocol
    p.plan[(1, 1)] = lambda q, s, pi: replace(price(q, s), reduced_cost_upper_bound=None)
    result = solve_root(p.grid, p.quadrants, time_limit_s=10)
    assert not result.converged


def test_one_eps_is_used_for_improvement_and_closure(protocol):
    p = protocol
    p.plan[(1, 1)] = lambda q, s, pi: replace(
        price(q, s), reduced_cost=EPS, reduced_cost_upper_bound=EPS,
    )
    result = solve_root(p.grid, p.quadrants, time_limit_s=10)
    assert result.converged
    assert not result.iterations[0].columns_found


def test_pricing_exception_is_recorded_and_cannot_certify_closure(protocol):
    p = protocol

    def fail(q, s, pi):
        raise RuntimeError("pricing unavailable")

    p.plan[(1, 2)] = fail
    result = solve_root(p.grid, p.quadrants, time_limit_s=10)
    assert not result.converged
    assert "pricing unavailable" in result.iterations[0].pricings[1].error_message
    assert len(p.calls) == 4


@pytest.mark.parametrize("budget", [-1, True, None, float("inf"), float("nan")])
def test_invalid_global_budget_is_rejected(geometry, budget):
    with pytest.raises(ValueError, match="time_limit_s"):
        solve_root(*geometry, time_limit_s=budget)


def enumerate_configurations(grid, quadrants):
    """Independent exhaustive oracle used only for tiny integration tests."""
    all_configs = []
    for quadrant in quadrants:
        placements = grid.placements_in(quadrant)
        assert len(placements) <= 9
        for mask in range(1 << len(placements)):
            selected = tuple(p for i, p in enumerate(placements) if mask & (1 << i))
            if all(a.x + a.width <= b.x or b.x + b.width <= a.x
                   or a.y + a.height <= b.y or b.y + b.height <= a.y
                   for a, b in combinations(selected, 2)):
                all_configs.append(QuadrantConfiguration(quadrant, selected))
    return tuple(all_configs)


@pytest.mark.parametrize("dimensions, expected, columns", [
    ((3, 3, 1, 1), 9, 26), ((3, 4, 1, 1), 12, 92), ((4, 4, 1, 1), 16, 656),
])
def test_root_lp_matches_complete_enumerated_master(dimensions, expected, columns):
    grid = generate_global_discretization(*dimensions)
    quadrants = build_quadrants(*dimensions, alpha=0.5).quadrants
    full_pool = enumerate_configurations(grid, quadrants)
    assert len(full_pool) == columns
    with RestrictedMasterBuilder(grid, quadrants).build(full_pool, time_limit_s=2) as full:
        full_result = full.solve()
    result = solve_root(grid, quadrants, time_limit_s=10)
    assert result.error_message is None
    assert result.converged
    assert result.lp_is_current
    assert full_result.proven_optimal
    assert result.objective_value == pytest.approx(full_result.objective_value)
    assert result.objective_value == pytest.approx(expected)
    objectives = [row.rmp.objective_value for row in result.iterations]
    assert all(b >= a - EPS for a, b in zip(objectives, objectives[1:]))
    assert len(set(result.configurations)) == len(result.configurations)
    for row in result.iterations:
        assert len(row.pricings) == 4
        assert all(record.master_revision == row.master_revision for record in row.pricings)
        assert row.pool_after == row.pool_before + len(row.columns_added)
        assert row.iteration_time_s >= 0
    if dimensions == (3, 3, 1, 1):
        for row in result.iterations:
            print("TRACE", row.iteration, "RMP", row.rmp.objective_value,
                  "sigma", row.sigma, "nonzero_pi", row.nonzero_pi_count)
            for record in row.pricings:
                pricing = record.result
                print("  Q", record.quadrant, "rc", pricing.reduced_cost,
                      "ub", pricing.reduced_cost_upper_bound, "raw", pricing.raw_cplex_status,
                      "added", record.added, "duplicate", record.duplicate,
                      "configuration", pricing.configuration.placements)
        print("COMPLETE MASTER", columns, "columns, LP", full_result.objective_value)


def test_real_root_with_default_alpha(geometry):
    grid = generate_global_discretization(6, 6, 1, 1)
    quadrants = build_quadrants(6, 6, 1, 1).quadrants
    result = solve_root(grid, quadrants, time_limit_s=5)
    assert result.converged
    assert result.objective_value == 36
    assert result.lp_is_current
