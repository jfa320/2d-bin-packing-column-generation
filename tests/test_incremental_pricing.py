import time
from contextlib import nullcontext
from queue import Queue

import pytest

from config import get_instance
from helper_methods import validate_feasibility
from models.column_generation import column_generation_solver as cg
from models.column_generation.column_generation_solver import (
    execute_with_time_limit, orchestrator,
)
from models.column_generation.orchestrator_services import calculate_slice_height
from models.column_generation.slave_problem import (
    IncrementalPricingModel, create_slave_model, PricingStateError,
    temporary_pricing_changes,
)
from models.common.position_generator import generate_positions_xym
from objects.ConfigData import ConfigData


@pytest.fixture(params=[(6, 4, 3, 2), (7, 5, 3, 2), (6, 6, 2, 2)])
def geometry(request):
    width, height, item_width, item_height = request.param
    xy_x, xy_y = generate_positions_xym(width, height, item_width, item_height)
    return (3, xy_x, xy_y, width, item_height, item_width, height,
            calculate_slice_height(width, height, item_width, item_height))


def fresh_model(geometry, duals):
    return create_slave_model(*geometry[:3], duals, *geometry[3:])


def quiet(model):
    for setter in (model.set_log_stream, model.set_results_stream,
                   model.set_warning_stream, model.set_error_stream):
        setter(None)
    model.parameters.threads.set(1)
    return model


def structure(model):
    names = model.variables.get_names()
    rows = {
        name: (sense, rhs, sorted((names[i], value) for i, value in zip(row.ind, row.val)))
        for name, sense, rhs, row in zip(
            model.linear_constraints.get_names(), model.linear_constraints.get_senses(),
            model.linear_constraints.get_rhs(), model.linear_constraints.get_rows())
    }
    return (names, model.variables.get_types(), model.variables.get_lower_bounds(),
            model.variables.get_upper_bounds(), model.objective.get_sense(), rows)


def dual_sequence(geometry):
    width, height = geometry[3], geometry[6]
    area = geometry[4] * geometry[5]
    return [
        {"pi": {}},
        {"pi": {f"({x},{y})": 1.0 / area
                for x in range(width) for y in range(height)}},
        {"pi": {"(0,0)": 0.2, "(1,0)": 1.5, "(2,1)": 0.9}},
        {"pi": {f"({x},{y})": 2.0
                for x in range(width) for y in range(height)}},
        {"pi": {}},
    ]


def test_reused_structure_and_objective_match_fresh_models(geometry):
    session = IncrementalPricingModel(*geometry)
    original = None
    try:
        for duals in dual_sequence(geometry):
            reused = session.prepare(duals)
            if original is None:
                original = reused
            reference = fresh_model(geometry, duals)
            try:
                assert reused is original
                assert structure(reused) == structure(reference)
                assert reused.objective.get_linear() == pytest.approx(reference.objective.get_linear())
            finally:
                reference.end()
        assert session.build_count == 1
    finally:
        session.close()
    assert session.model is None
    session.close()  # Closing an already closed session is safe.


def test_repeated_solves_match_fresh_optima_and_bounds(geometry):
    session = IncrementalPricingModel(*geometry)
    try:
        for duals in dual_sequence(geometry):
            reused = quiet(session.prepare(duals))
            reference = quiet(fresh_model(geometry, duals))
            try:
                reused.solve()
                reference.solve()
                assert reused.parameters.advance.get() == 0
                assert reused.solution.get_status() in {101, 102}
                assert reference.solution.get_status() in {101, 102}
                assert reused.solution.get_objective_value() == pytest.approx(
                    reference.solution.get_objective_value(), abs=1e-8)
                assert reused.solution.MIP.get_best_objective() == pytest.approx(
                    reference.solution.MIP.get_best_objective(), abs=1e-8)
            finally:
                reference.end()
        assert session.build_count == 1
    finally:
        session.close()


def test_update_overwrites_zero_coefficients_and_window_objective(geometry):
    session = IncrementalPricingModel(*geometry)
    try:
        model = session.prepare({"pi": {}})
        model.objective.set_linear([(i, 123.0) for i in range(model.variables.get_num())])
        model.objective.set_sense(model.objective.sense.minimize)
        updated = session.prepare(dual_sequence(geometry)[1])
        assert updated is model
        assert updated.objective.get_linear() == pytest.approx([0.0] * model.variables.get_num())
        assert updated.objective.get_sense() == updated.objective.sense.maximize
    finally:
        session.close()


def test_partial_update_failure_closes_session_without_rebuilding(geometry, monkeypatch):
    session = IncrementalPricingModel(*geometry)
    try:
        old = session.prepare({"pi": {}})
        original_update = old.objective.set_linear

        def fail_after_first_coefficient(coefficients):
            original_update(coefficients[:1])
            raise RuntimeError("partial objective update")

        monkeypatch.setattr(old.objective, "set_linear", fail_after_first_coefficient)
        duals = dual_sequence(geometry)[2]
        with pytest.raises(PricingStateError, match="partial objective update"):
            session.prepare(duals)
        assert session.model is None
        assert session.build_count == 1
        with pytest.raises(PricingStateError, match="closed"):
            session.prepare(duals)
        assert session.build_count == 1
    finally:
        session.close()


def test_unexpected_temporary_row_fails_without_rebuilding(geometry):
    session = IncrementalPricingModel(*geometry)
    try:
        old = session.prepare({"pi": {}})
        old.linear_constraints.add(
            lin_expr=[[[0], [1.0]]], senses=["L"], rhs=[0.0], names=["unexpected_cut"])
        with pytest.raises(PricingStateError, match="structure was modified"):
            session.prepare({"pi": {}})
        assert session.model is None
        assert session.build_count == 1
    finally:
        session.close()


@pytest.mark.parametrize("fail", [False, True])
def test_nested_temporary_changes_restore_same_model_even_on_failure(geometry, fail):
    session = IncrementalPricingModel(*geometry)
    try:
        model = session.prepare({"pi": {}})
        baseline, coefficients = structure(model), model.objective.get_linear()
        with pytest.raises(ValueError, match="auxiliary failed") if fail else nullcontext():
            with temporary_pricing_changes(model):
                model.linear_constraints.add(
                    lin_expr=[[[0], [1.0]]], senses=["L"], rhs=[0.0], names=["outer_cut"])
                outer_count = model.linear_constraints.get_num()
                with temporary_pricing_changes(model):
                    model.linear_constraints.add(
                        lin_expr=[[[0], [1.0]]], senses=["G"], rhs=[0.0], names=["inner_cut"])
                    model.objective.set_linear([(0, 123.0)])
                    model.objective.set_sense(model.objective.sense.minimize)
                assert model.linear_constraints.get_num() == outer_count
                assert "outer_cut" in model.linear_constraints.get_names()
                assert model.objective.get_linear() == coefficients
                if fail:
                    raise ValueError("auxiliary failed")
        assert structure(model) == baseline
        assert model.objective.get_linear() == coefficients
        assert session.prepare({"pi": {}}) is model
        assert session.build_count == 1
    finally:
        session.close()


def test_failed_temporary_cleanup_is_fatal_without_rebuilding(geometry, monkeypatch):
    session = IncrementalPricingModel(*geometry)
    try:
        model = session.prepare({"pi": {}})
        def fail(*args):
            raise RuntimeError("cannot remove cut")
        monkeypatch.setattr(model.linear_constraints, "delete", fail)
        with pytest.raises(PricingStateError, match="cannot remove cut"):
            with temporary_pricing_changes(model):
                model.linear_constraints.add(
                    lin_expr=[[[0], [1.0]]], senses=["L"], rhs=[0.0], names=["failed_cut"])
        with pytest.raises(PricingStateError, match="structure was modified"):
            session.prepare({"pi": {}})
        assert session.build_count == 1
        assert session.model is None
    finally:
        session.close()


@pytest.mark.parametrize("fail", [False, True])
def test_phase_two_restores_structure_and_objective_on_same_instance(geometry, monkeypatch, fail):
    from models.column_generation.slave_problem import solve_slave_model, refine_slave_model
    session = IncrementalPricingModel(*geometry)
    queue = Queue()
    try:
        model = quiet(session.prepare({"pi": {}}))
        baseline, coefficients = structure(model), model.objective.get_linear()
        width, item_height, item_width, _, slice_height = geometry[3:]
        primary = solve_slave_model(model, queue, None, width, item_height,
                                    item_width, slice_height, use_pricing_second_phase=False)
        if fail:
            def fail_solve():
                raise RuntimeError("phase two failed")
            monkeypatch.setattr(model, "solve", fail_solve)
        result = refine_slave_model(model, queue, width, item_height,
                                    item_width, slice_height, primary)
        assert result[1] == pytest.approx(primary[1])
        assert structure(model) == baseline
        assert model.objective.get_linear() == coefficients
        assert session.prepare({"pi": {}}) is model
        assert session.build_count == 1
        if fail:
            assert any("phase two failed" in message.get("error", "")
                       for message in list(queue.queue))
    finally:
        session.close()


def test_phase_two_prefers_more_items_at_equal_original_value():
    from objects import Item, Slice
    from models.column_generation.slave_problem import refine_slave_model
    session = IncrementalPricingModel(2, [(0, 0), (1, 0), (2, 0)], [], 4, 1, 2, 1, 1)
    duals = {"pi": {"(0,0)": 0.5, "(3,0)": 0.5}}
    try:
        model = quiet(session.prepare(duals))
        baseline, coefficients = structure(model), model.objective.get_linear()
        # Centered single rectangle and two side-by-side rectangles both score 1.
        incumbent = Slice(height=1, width=4, items=[
            Item(height=1, width=2, position_x=1, position_y=0)])
        result = refine_slave_model(model, Queue(), 4, 1, 2, 1,
                                    (incumbent, 1.0, ["z_x_1_0"]))
        assert len(result[0].get_items()) == 2
        assert result[1] == pytest.approx(1.0)
        assert set(result[2]) == {"z_x_0_0", "z_x_2_0"}
        assert structure(model) == baseline
        assert model.objective.get_linear() == coefficients
        assert session.prepare(duals) is model
        assert session.build_count == 1
    finally:
        session.close()


@pytest.mark.parametrize("dimensions", [(6, 4, 2, 3), (4, 6, 3, 2), (4, 6, 2, 3)])
def test_reuse_preserves_normalized_output_feasibility(dimensions):
    value, slices = orchestrator(
        Queue(), None, 10, time.perf_counter(), ConfigData(*dimensions),
        return_solution=True, use_pricing_second_phase=False,
                              use_pricing_final_enrichment=False,
                              use_pricing_duplicate_retries=False, pricing_mode="reuse")
    assert value == 4
    validate_feasibility(slices, dimensions[0], dimensions[1], value)


@pytest.mark.parametrize("pricing_mode", [None, "reuse"], ids=["default", "reuse"])
@pytest.mark.parametrize("case_name, expected", [("case1", 4), ("case7", 7)])
def test_pricing_mode_reaches_spawned_solver(pricing_mode, case_name, expected):
    options = {} if pricing_mode is None else {"pricing_mode": pricing_mode}
    result = execute_with_time_limit(
        20, instance=get_instance(case_name), use_pricing_second_phase=False,
                                              use_pricing_final_enrichment=False,
                                              use_pricing_duplicate_retries=False,
        **options)
    assert result.execution.termination_status == "Normal"
    assert result.execution.objective_value == expected
    assert result.metrics.lp_value == pytest.approx(expected)
    assert result.diagnostics.lp_convergence_proven
    assert result.diagnostics.cg_stop_reason == "pricing_converged"
    assert result.iterations
    for field in ("pricing_build_time_s", "pricing_solve_time_s"):
        assert sum(getattr(row, field) for row in result.iterations) == pytest.approx(
            getattr(result.metrics, field))


@pytest.mark.parametrize("heuristics", [None, False], ids=["configured-base", "explicit-base"])
def test_default_base_call_reuses_one_real_model(monkeypatch, heuristics):
    sessions, prepared_models = [], []

    class ObservedPricing(IncrementalPricingModel):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            sessions.append(self)

        def prepare(self, duals):
            model = super().prepare(duals)
            prepared_models.append(model)
            return model

    monkeypatch.setattr(cg, "IncrementalPricingModel", ObservedPricing)
    result = orchestrator(
        Queue(), None, 10, time.perf_counter(), ConfigData(6, 4, 2, 3),
        # This control checks one exact preparation per iteration.
        return_structured=True, use_pricing_second_phase=heuristics,
                                use_pricing_final_enrichment=heuristics,
                                use_pricing_duplicate_retries=heuristics, use_greedy_pricing=False)
    assert result.execution.termination_status == "Normal"
    assert result.execution.objective_value == 4
    assert len(sessions) == 1
    assert sessions[0].build_count == 1
    assert len(prepared_models) == result.metrics.cg_iterations > 1
    assert all(model is prepared_models[0] for model in prepared_models)
    assert sessions[0].model is None


@pytest.mark.parametrize("fail_auxiliary", [False, True])
@pytest.mark.parametrize("second_phase", [False, True])
def test_retries_and_extras_share_one_model_and_clean_up_on_error(monkeypatch, fail_auxiliary, second_phase):
    from objects import Item, Slice
    from utils.status_normalizer import map_cplex_lp_status, map_cplex_mip_status

    def column(x):
        return Slice(height=1, width=4, items=[
            Item(height=1, width=1, position_x=x, position_y=0)])

    seed = column(0)
    monkeypatch.setattr(cg, "generate_initial_slices", lambda *args: [seed])
    monkeypatch.setattr(cg, "export_final_layout", lambda *args: None)
    monkeypatch.setattr(cg, "refine_slave_model",
                        lambda model, queue, w, h, iw, sh, primary, remaining: primary)
    rounds = [0]
    def master(model, progress, manual, relaxed, initial):
        if relaxed:
            rounds[0] += 1
        duals = {"pi": {} if rounds[0] == 1 else {
            f"({x},{y})": 1.0 for x in range(4) for y in range(4)}}
        progress.put({"phase": "lp" if relaxed else "ip", "objective": 2.0,
                      "state": map_cplex_lp_status(1) if relaxed else map_cplex_mip_status(101),
                      "raw_status": 1 if relaxed else 101})
        return 2.0, duals if relaxed else None, []
    monkeypatch.setattr(cg, "solve_master_model", master)
    sessions, calls, closed_shapes = [], [], []
    class ObservedPricing(IncrementalPricingModel):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            sessions.append(self)
        def close(self):
            if self.model is not None:
                closed_shapes.append(structure(self.model))
            super().close()
    monkeypatch.setattr(cg, "IncrementalPricingModel", ObservedPricing)
    responses = iter([(seed, 1.0, ["z_x_0_0"]),
                      (column(1), 1.0, ["z_x_1_0"]),
                      (column(2), 0.0, ["z_x_2_0"]),
                      (column(3), 0.0, ["z_x_3_0"]), (None, None, [])])
    baseline = []
    def pricing(model, progress, manual, *args, **kwargs):
        if not baseline:
            baseline.append(structure(model))
        cuts = [name for name in model.linear_constraints.get_names() if name.startswith("nogood_")]
        calls.append((model, len(cuts), model.parameters.threads.get(), model.parameters.randomseed.get()))
        if fail_auxiliary and len(calls) == 4:
            raise RuntimeError("auxiliary search failed")
        response = next(responses)
        raw = 101 if response[1] is not None else 103
        progress.put({"phase": "pricing", "objective": response[1], "best_bound": response[1],
                      "raw_status": raw, "state": map_cplex_mip_status(raw)})
        return response
    monkeypatch.setattr(cg, "solve_slave_model", pricing)
    result = orchestrator(Queue(), None, 10, time.perf_counter(), ConfigData(4, 4, 1, 1),
                          return_structured=True, use_pricing_second_phase=second_phase,
                          use_pricing_final_enrichment=True, use_pricing_duplicate_retries=True,
                          use_pricing_pool=False, use_greedy_pricing=False,
                          random_seed=7, threads=1)
    assert len(sessions) == sessions[0].build_count == 1
    assert all(call[0] is calls[0][0] for call in calls)
    assert [call[1] for call in calls] == ([0, 1, 0, 1] if fail_auxiliary else [0, 1, 0, 1, 2])
    assert all(call[2:] == (1, 7) for call in calls)
    assert closed_shapes == baseline
    assert result.diagnostics.pricing_objective == result.diagnostics.pricing_best_bound == 0.0
    assert result.diagnostics.lp_convergence_proven
    if fail_auxiliary:
        assert result.execution.termination_status == "Error"
        assert "auxiliary search failed" in result.execution.error_message
        assert result.diagnostics.interrupted_phase == "pricing"
    else:
        assert not result.execution.error_message
        assert result.diagnostics.cg_stop_reason == "pricing_converged"
