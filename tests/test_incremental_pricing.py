import time
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
    IncrementalPricingModel, create_slave_model,
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


def test_partial_update_failure_discards_model_and_rebuilds(geometry, monkeypatch, capsys):
    session = IncrementalPricingModel(*geometry)
    try:
        old = session.prepare({"pi": {}})
        original_update = old.objective.set_linear

        def fail_after_first_coefficient(coefficients):
            original_update(coefficients[:1])
            raise RuntimeError("partial objective update")

        monkeypatch.setattr(old.objective, "set_linear", fail_after_first_coefficient)
        duals = dual_sequence(geometry)[2]
        updated = session.prepare(duals)
        reference = fresh_model(geometry, duals)
        try:
            assert updated is not old
            assert session.build_count == 2
            assert structure(updated) == structure(reference)
            assert updated.objective.get_linear() == pytest.approx(reference.objective.get_linear())
        finally:
            reference.end()
        assert "partial objective update" in capsys.readouterr().out
    finally:
        session.close()


def test_unexpected_temporary_row_triggers_clean_rebuild(geometry):
    session = IncrementalPricingModel(*geometry)
    try:
        old = session.prepare({"pi": {}})
        old.linear_constraints.add(
            lin_expr=[[[0], [1.0]]], senses=["L"], rhs=[0.0], names=["unexpected_cut"])
        updated = session.prepare({"pi": {}})
        assert updated is not old
        assert "unexpected_cut" not in updated.linear_constraints.get_names()
        assert session.build_count == 2
    finally:
        session.close()


@pytest.mark.parametrize("dimensions", [(6, 4, 2, 3), (4, 6, 3, 2), (4, 6, 2, 3)])
def test_reuse_preserves_normalized_output_feasibility(dimensions):
    value, slices = orchestrator(
        Queue(), None, 10, time.perf_counter(), ConfigData(*dimensions),
        return_solution=True, finalization_heuristics=False, pricing_mode="reuse")
    assert value == 4
    validate_feasibility(slices, dimensions[0], dimensions[1], value)


@pytest.mark.parametrize("pricing_mode", [None, "rebuild", "reuse"], ids=["default", "rebuild", "reuse"])
@pytest.mark.parametrize("case_name, expected", [("case1", 4), ("case7", 7)])
def test_pricing_mode_reaches_spawned_solver(pricing_mode, case_name, expected):
    options = {} if pricing_mode is None else {"pricing_mode": pricing_mode}
    result = execute_with_time_limit(
        20, instance=get_instance(case_name), finalization_heuristics=False,
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
        return_structured=True, finalization_heuristics=heuristics)
    assert result.execution.termination_status == "Normal"
    assert result.execution.objective_value == 4
    assert len(sessions) == 1
    assert sessions[0].build_count == 1
    assert len(prepared_models) == result.metrics.cg_iterations > 1
    assert all(model is prepared_models[0] for model in prepared_models)
    assert sessions[0].model is None
