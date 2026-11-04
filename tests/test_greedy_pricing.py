from queue import Queue
from unittest.mock import Mock

import pytest

from models.column_generation import column_generation_solver as cg
from models.column_generation import greedy_pricing as greedy
from models.column_generation.greedy_pricing import GreedyPricingHeuristic
from models.column_generation.slave_problem import create_slave_model
from models.column_generation.solution_pool import (
    InvalidPoolSolution, PricingGeometry, candidate_to_slice, slice_master_key,
)
from models.common.position_generator import generate_positions_xym
from objects import Item, Slice
from objects.ConfigData import ConfigData
from utils.status_normalizer import map_cplex_lp_status, map_cplex_mip_status


def test_score_uses_every_covered_cell_and_orientation():
    geometry = PricingGeometry(5, 4, 3, 2, 1)
    heuristic = GreedyPricingHeuristic(geometry, [(0, 0)], [(0, 0)])
    duals = {"pi": {"(2,0)": 0.6, "(0,2)": 0.2, "(1,1)": 0.1}}
    assert heuristic.score_placement((0, 0, "x"), duals) == pytest.approx(0.3)
    assert heuristic.score_placement((0, 0, "y"), duals) == pytest.approx(0.7)
    assert heuristic.score_placement((0, 0, "x"), {"pi": {}}) == 1.0


@pytest.mark.parametrize("dimensions", [(6, 4, 3, 2), (7, 5, 3, 2), (6, 6, 2, 2)])
def test_domain_and_scores_match_exact_pricing_coefficients(dimensions):
    width, height, w, h = dimensions
    xy_x, xy_y = generate_positions_xym(*dimensions)
    # Also exercise the builder's upper-bound filters.
    xy_x.add((width, 0))
    xy_y.add((0, height))
    geometry = PricingGeometry(width, height, w, h, 2)
    heuristic = GreedyPricingHeuristic(geometry, xy_x, xy_y)
    for duals in ({"pi": {"(0,0)": 0.2, "(1,0)": 1.5, "(2,1)": 0.9}},
                  {"pi": {}}):
        model = create_slave_model(1, xy_x, xy_y, duals, width, h, w, height, 2)
        try:
            coefficients = dict(zip(model.variables.get_names(), model.objective.get_linear()))
            assert {f"z_{t}_{a}_{b}" for a, b, t in heuristic.cells_by_placement} == {
                name for name in coefficients if name.startswith("z_")}
            for placement in heuristic.cells_by_placement:
                a, b, t = placement
                assert heuristic.score_placement(placement, duals) == coefficients[f"z_{t}_{a}_{b}"]
        finally:
            model.end()


def test_selects_nonoverlapping_placements_with_deterministic_ties():
    geometry = PricingGeometry(5, 3, 2, 1, 1)
    positions = [(3, 0), (1, 0), (0, 0)]
    first = GreedyPricingHeuristic(geometry, positions, []).find_column({"pi": {}}, set())
    second = GreedyPricingHeuristic(geometry, reversed(positions), []).find_column({"pi": {}}, set())
    assert first == second
    assert first.placements == ((0, 0, "x"), (3, 0, "x"))
    assert len(first.cells) == 4


def test_rejects_window_boundary_but_allows_smaller_vertical_spread():
    geometry = PricingGeometry(4, 4, 1, 1, 2)
    candidate = GreedyPricingHeuristic(geometry, [(0, 0), (1, 1), (2, 2)], []).find_column(
        {"pi": {}}, set())
    assert candidate.placements == ((0, 0, "x"), (1, 1, "x"))


def test_window_can_extend_below_first_selected_placement():
    geometry = PricingGeometry(3, 4, 1, 1, 2)
    candidate = GreedyPricingHeuristic(geometry, [(0, 1), (1, 0)], []).find_column(
        {"pi": {"(1,0)": 0.2}}, set())
    assert candidate.placements == ((0, 1, "x"), (1, 0, "x"))


def test_rotated_item_may_extend_above_the_start_window():
    geometry = PricingGeometry(4, 4, 3, 1, 1)
    duals = {"pi": {"(0,3)": 0.2}}
    candidate = GreedyPricingHeuristic(geometry, [], [(0, 1)]).find_column(duals, set())
    assert candidate.placements == ((0, 1, "y"),)
    assert candidate.value == pytest.approx(0.8)
    slice_ = candidate_to_slice(candidate, geometry)
    assert cg.calculate_real_reduced_cost(slice_, duals, 3, 1)[0] == pytest.approx(candidate.value)
    assert slice_.get_items()[0].get_height() == 3


@pytest.mark.parametrize("price", [1.0, 2.0])
def test_rejects_zero_and_negative_scores(price):
    geometry = PricingGeometry(2, 2, 1, 1, 1)
    assert GreedyPricingHeuristic(geometry, [(0, 0)], []).find_column(
        {"pi": {"(0,0)": price}}, set()) is None


def test_nonpositive_placements_cannot_reduce_a_positive_selection():
    geometry = PricingGeometry(3, 2, 1, 1, 1)
    candidate = GreedyPricingHeuristic(geometry, [(0, 0), (1, 0), (2, 0)], []).find_column(
        {"pi": {"(1,0)": 1.0, "(2,0)": 5.0}}, set())
    assert candidate.placements == ((0, 0, "x"),)
    assert candidate.value == 1.0


def test_applies_eps_to_total_and_allocates_no_domain_ids_before_acceptance():
    geometry = PricingGeometry(2, 2, 1, 1, 1)
    heuristic = GreedyPricingHeuristic(geometry, [(0, 0), (1, 0)], [])
    ids = (Item._id_counter, Slice._id_counter)
    duals = {"pi": {"(0,0)": 1 - 0.75e-9, "(1,0)": 1 - 0.75e-9}}
    candidate = heuristic.find_column(duals, set())
    assert candidate is not None and candidate.value > cg.EPS
    assert heuristic.find_column(duals, set(), eps=2e-9) is None
    assert heuristic.find_column(duals, {candidate.master_key}) is None
    assert (Item._id_counter, Slice._id_counter) == ids


def test_rejects_master_equivalent_column_even_with_different_tiling():
    geometry = PricingGeometry(2, 2, 2, 1, 2)
    vertical = Slice(height=2, width=2, items=[
        Item(height=2, width=1, rotated=True, position_x=x, position_y=0)
        for x in (0, 1)])
    heuristic = GreedyPricingHeuristic(geometry, [(0, 0), (0, 1)], [])
    assert heuristic.find_column({"pi": {}}, {slice_master_key(vertical)}) is None


@pytest.mark.parametrize("price", [float("nan"), float("inf")])
def test_nonfinite_scores_return_no_column(price):
    heuristic = GreedyPricingHeuristic(PricingGeometry(2, 2, 1, 1, 1), [(0, 0)], [])
    assert heuristic.find_column({"pi": {"(0,0)": price}}, set()) is None


def test_final_validation_failure_returns_no_column(monkeypatch):
    def invalid(*args):
        raise InvalidPoolSolution("invalid selection")
    monkeypatch.setattr(greedy, "candidate_from_values", invalid)
    heuristic = GreedyPricingHeuristic(PricingGeometry(2, 2, 1, 1, 1), [(0, 0)], [])
    assert heuristic.find_column({"pi": {}}, set()) is None


@pytest.fixture
def run_loop(monkeypatch):
    clock = [0.0]
    events, received_duals, exact_models = [], [], []
    monkeypatch.setattr(cg.time, "perf_counter", lambda: clock[0])
    monkeypatch.setattr(cg, "generate_positions_xym", lambda *a: ({(0, 0), (1, 0)}, set()))
    monkeypatch.setattr(cg, "generate_initial_slices", lambda *a: [Slice(height=1, width=2, items=[
        Item(height=1, width=1, position_x=0, position_y=0)])])
    monkeypatch.setattr(cg, "create_master_model", lambda *a: object())
    updates = []
    class IncrementalMaster:
        def __init__(self, *a):
            pass
        def add_slice(self, slice_):
            updates.append(slice_)
    monkeypatch.setattr(cg, "IncrementalMasterModel", IncrementalMaster)
    monkeypatch.setattr(cg, "export_final_layout", lambda *a: None)
    original_find = GreedyPricingHeuristic.find_column
    def observed_find(self, duals, *a, **k):
        received_duals.append(duals)
        clock[0] += 0.25
        events.append("greedy")
        return original_find(self, duals, *a, **k)
    monkeypatch.setattr(GreedyPricingHeuristic, "find_column", observed_find)

    def run(duals, *, exact_status=101, exact_bound=0.0, exact_responses=None, **kwargs):
        dual_iterator = iter(duals)
        responses = iter(exact_responses) if exact_responses is not None else None
        def master(model, progress, manual, relaxed, initial):
            with cg.timed_component(progress, "master_solve"):
                clock[0] += 1
            prices = next(dual_iterator) if relaxed else None
            value = None if relaxed and prices is None else 2.0
            raw = (3 if prices is None else 1) if relaxed else 101
            state = map_cplex_lp_status(raw) if relaxed else map_cplex_mip_status(raw)
            progress.put({"phase": "lp" if relaxed else "ip", "objective": value,
                          "raw_status": raw, "state": state})
            events.append("rmp" if relaxed else "ip")
            return value, prices, []
        def build(*a):
            events.append("exact_build")
            model = object()
            exact_models.append(model)
            return model
        def exact(model, progress, *a, **k):
            events.append("exact_solve")
            with cg.timed_component(progress, "pricing_solve"):
                clock[0] += 0.5
                response = next(responses) if responses is not None else (None, 0.0, [])
            progress.put({"phase": "pricing", "objective": response[1], "best_bound": (
                              response[1] if exact_status == 101 else exact_bound),
                          "raw_status": exact_status, "state": map_cplex_mip_status(exact_status)})
            return response
        monkeypatch.setattr(cg, "solve_master_model", master)
        monkeypatch.setattr(cg, "create_slave_model", build)
        monkeypatch.setattr(cg, "solve_slave_model", exact)
        return cg.orchestrator(Queue(), None, 60, 0, ConfigData(2, 2, 1, 1),
                               return_structured=True, pricing_mode="rebuild",
                               use_pricing_pool=False,
                               finalization_heuristics=kwargs.pop("finalization_heuristics", False),
                               **kwargs)
    run.events, run.duals, run.models = events, received_duals, exact_models
    run.updates = updates
    return run


def test_accepted_column_skips_exact_then_fallback_can_certify(run_loop):
    result = run_loop([{"pi": {"(0,0)": 1.0}},
                       {"pi": {"(0,0)": 1.0, "(1,0)": 1.0}}])
    assert run_loop.events == ["rmp", "greedy", "rmp", "greedy", "exact_build", "exact_solve", "ip"]
    assert len(run_loop.updates) == 1
    assert result.metrics.cg_iterations == 2
    assert result.metrics.generated_columns == 1
    assert result.metrics.greedy_pricing_calls == 2
    assert result.metrics.greedy_pricing_accepted == result.metrics.greedy_pricing_fallbacks == 1
    assert result.metrics.exact_pricing_calls_avoided == 1
    assert result.metrics.greedy_pricing_time_s == 0.5
    first, second = result.iterations
    assert first.stop_reason == "greedy_column_added"
    assert first.completed and first.pricing_calls == 0
    assert first.pricing_status.raw_cplex_status is None
    assert first.pricing_objective is first.pricing_best_bound is None
    assert second.pricing_calls == 1
    assert second.pricing_status.raw_cplex_status == 101
    assert result.diagnostics.lp_convergence_proven
    assert result.diagnostics.convergence_basis == "optimal_pricing"
    for field in ("greedy_pricing_calls", "greedy_pricing_accepted", "greedy_pricing_fallbacks",
                  "greedy_pricing_time_s", "exact_pricing_calls_avoided"):
        assert sum(getattr(row, field) for row in result.iterations) == getattr(result.metrics, field)


@pytest.mark.parametrize("prices", [
    {"(0,0)": 1.0, "(1,0)": 1.0},  # No positive score.
    {"(1,0)": 1.0},  # Positive candidate equals the seed column.
])
def test_failed_or_duplicate_greedy_uses_exact_fallback(run_loop, prices):
    result = run_loop([{"pi": prices}])
    assert len(run_loop.models) == 1
    assert result.metrics.greedy_pricing_fallbacks == 1
    assert result.metrics.greedy_pricing_accepted == result.metrics.exact_pricing_calls_avoided == 0
    assert result.diagnostics.lp_convergence_proven


def test_validation_failure_in_greedy_uses_exact_fallback(run_loop, monkeypatch):
    monkeypatch.setattr(greedy, "candidate_from_values", Mock(side_effect=InvalidPoolSolution("bad")))
    result = run_loop([{"pi": {}}])
    assert len(run_loop.models) == result.metrics.greedy_pricing_fallbacks == 1
    assert result.diagnostics.lp_convergence_proven


def test_exact_columns_also_enter_the_greedy_duplicate_registry(run_loop, monkeypatch):
    original_find = GreedyPricingHeuristic.find_column
    calls = []
    def fail_first(self, *a, **k):
        calls.append(True)
        return None if len(calls) == 1 else original_find(self, *a, **k)
    monkeypatch.setattr(GreedyPricingHeuristic, "find_column", fail_first)
    exact_column = Slice(height=1, width=2, items=[
        Item(height=1, width=1, position_x=1, position_y=0)])
    exact_column.set_id(1000)
    prices = {"pi": {"(0,0)": 1.0}}
    result = run_loop([prices, prices], exact_responses=[
        (exact_column, 1.0, ["z_x_1_0"]), (None, 0.0, [])])
    assert result.metrics.greedy_pricing_fallbacks == 2
    assert result.metrics.greedy_pricing_accepted == 0
    assert result.metrics.generated_columns == 1
    assert len(run_loop.models) == 2
    assert result.diagnostics.lp_convergence_proven


def test_greedy_acceptance_followed_by_lp_failure_cannot_certify(run_loop):
    result = run_loop([{"pi": {"(0,0)": 1.0}}, None])
    assert result.metrics.greedy_pricing_accepted == 1
    assert run_loop.models == []
    assert not result.diagnostics.lp_convergence_proven
    assert result.diagnostics.convergence_basis is None
    assert result.diagnostics.pricing_objective is result.diagnostics.pricing_best_bound is None


@pytest.mark.parametrize("bound,proven", [(2.0, False), (0.0, True)])
def test_greedy_failure_needs_exact_evidence_for_closure(run_loop, bound, proven):
    result = run_loop([{"pi": {"(0,0)": 1.0, "(1,0)": 1.0}}],
                      exact_status=107, exact_bound=bound)
    assert len(run_loop.models) == 1
    assert result.diagnostics.lp_convergence_proven is proven
    assert result.diagnostics.convergence_basis == ("pricing_upper_bound" if proven else None)


def test_greedy_uses_original_duals_even_when_exact_duals_are_stabilized(run_loop, monkeypatch):
    original = {"pi": {"(0,0)": 1.0}}
    stabilize = Mock(return_value={"pi": {"(0,0)": 100.0, "(1,0)": 100.0}})
    monkeypatch.setattr(cg, "stabilize_duals", stabilize)
    result = run_loop([original, None], finalization_heuristics=None)
    assert stabilize.call_count == 1
    assert run_loop.duals == [original] and run_loop.duals[0] is original
    assert result.metrics.greedy_pricing_accepted == 1
    assert run_loop.models == []


def test_disabled_greedy_preserves_exact_path(run_loop):
    result = run_loop([{"pi": {}}], use_greedy_pricing=False)
    assert run_loop.duals == []
    assert len(run_loop.models) == 1
    assert result.metrics.greedy_pricing_calls == result.metrics.greedy_pricing_time_s == 0
    assert result.diagnostics.lp_convergence_proven


def test_interrupted_greedy_time_is_accounted_without_a_certificate(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(cg.time, "perf_counter", lambda: clock[0])
    progress = cg._CGProgress(Queue(), "greedy", 0.0, True)
    progress.begin_iteration(1)
    progress.start_phase("pricing")
    progress.record_counts({"greedy_pricing_calls": 1})
    progress.start_component("greedy_pricing")
    clock[0] = 0.5
    snapshot = progress.result()
    result = cg._account_interruption(snapshot, 1.0, "wall_clock_timeout")
    assert result.metrics.greedy_pricing_time_s == 1.0
    assert result.iterations[0].greedy_pricing_time_s == 1.0
    assert result.metrics.greedy_pricing_calls == 1
    assert result.metrics.greedy_pricing_fallbacks == result.metrics.greedy_pricing_accepted == 0
    assert not result.diagnostics.lp_convergence_proven


@pytest.mark.parametrize("enabled", [False, True])
@pytest.mark.parametrize("pool", [False, True])
def test_greedy_option_and_metrics_survive_spawn(enabled, pool):
    result = cg.execute_with_time_limit(
        15, instance=dict(case_name="greedy_spawn", bin_width=6, bin_height=4,
                          item_width=3, item_height=2), use_greedy_pricing=enabled,
        use_pricing_pool=pool, finalization_heuristics=False, threads=1)
    assert result.execution.termination_status == "Normal"
    assert result.metrics.restricted_integer_master == 4
    assert (result.metrics.greedy_pricing_calls > 0) is enabled
    assert result.metrics.exact_pricing_calls_avoided == result.metrics.greedy_pricing_accepted
    assert result.diagnostics.lp_convergence_proven


def test_greedy_totals_survive_disabled_iteration_recording(run_loop):
    result = run_loop([{"pi": {"(0,0)": 1.0}},
                       {"pi": {"(0,0)": 1.0, "(1,0)": 1.0}}], record_iterations=False)
    assert result.iterations == []
    assert result.metrics.greedy_pricing_calls == 2
    assert result.metrics.greedy_pricing_accepted == result.metrics.greedy_pricing_fallbacks == 1
    assert result.metrics.greedy_pricing_time_s == 0.5
    assert result.diagnostics.lp_convergence_proven


@pytest.mark.parametrize("value", [1, "true"])
def test_invalid_greedy_option_is_rejected_before_solving(run_loop, value):
    result = run_loop([], use_greedy_pricing=value)
    assert result.execution.termination_status == "Error"
    assert "use_greedy_pricing must be a boolean" in result.execution.error_message
    assert run_loop.events == []


@pytest.mark.parametrize("flag", [False, True])
@pytest.mark.parametrize("override", [None, False, True])
def test_greedy_config_and_explicit_override(run_loop, monkeypatch, flag, override):
    monkeypatch.setattr(cg.config, "USE_GREEDY_PRICING", flag)
    options = {} if override is None else {"use_greedy_pricing": override}
    result = run_loop([{"pi": {"(0,0)": 1.0, "(1,0)": 1.0}}], **options)
    enabled = flag if override is None else override
    assert (result.metrics.greedy_pricing_calls > 0) is enabled
    assert len(run_loop.models) == 1
    assert result.diagnostics.lp_convergence_proven


@pytest.mark.parametrize("flag", [False, True])
@pytest.mark.parametrize("override", [None, False, True])
def test_greedy_config_selection_survives_spawn(monkeypatch, flag, override):
    monkeypatch.setattr(cg.config, "USE_GREEDY_PRICING", flag)
    result = cg.execute_with_time_limit(
        15, instance=dict(case_name="greedy_config_spawn", bin_width=6, bin_height=4,
                          item_width=3, item_height=2), use_greedy_pricing=override,
        use_pricing_pool=False, finalization_heuristics=False, threads=1)
    enabled = flag if override is None else override
    assert result.execution.termination_status == "Normal"
    assert result.metrics.restricted_integer_master == 4
    assert (result.metrics.greedy_pricing_calls > 0) is enabled
    assert result.diagnostics.lp_convergence_proven


@pytest.mark.parametrize("value", [None, "false"])
def test_invalid_greedy_config_is_rejected_before_solving(run_loop, monkeypatch, value):
    monkeypatch.setattr(cg.config, "USE_GREEDY_PRICING", value)
    result = run_loop([])
    assert "USE_GREEDY_PRICING must be a boolean" in result.execution.error_message
    assert run_loop.events == []
