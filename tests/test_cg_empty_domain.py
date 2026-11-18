"""Empty packing certificates and LP/MIP status regression coverage."""

import time
from multiprocessing import get_context
from queue import Queue
from unittest.mock import Mock

import cplex
import pytest

from models.column_generation import column_generation_solver as cg
from models.column_generation import slave_problem
from models.column_generation.orchestrator_services import NormalizedProblem
from objects.ConfigData import ConfigData
from utils.execution_result import SolverPhaseStatus
from utils.paver_constants import PaverConstants as PAVER


NO_FIT_CASES = [(5, 5, 6, 1), (5, 5, 11, 1), (5, 2, 3, 3), (2, 2, 3, 2)]
OPTIONS = [
    {},
    dict(initialization="mixed", use_greedy_pricing=False, use_pricing_pool=True,
         use_pricing_second_phase=True, use_pricing_final_enrichment=True,
         use_pricing_duplicate_retries=True, pricing_mode="reuse"),
]


def assert_empty_certificate(result):
    assert result.execution.objective_value == 0
    assert result.execution.model_status == PAVER.MODEL_STATUS_OPTIMAL
    assert result.execution.termination_status == PAVER.TERMINATION_NORMAL
    assert result.execution.error_message is None
    assert result.execution.raw_cplex_status is None
    assert result.metrics.lp_value == 0
    assert result.metrics.restricted_integer_master == 0
    assert result.metrics.initial_lp_value is None
    assert result.metrics.initial_columns == result.metrics.pool_size == 0
    assert result.metrics.cg_iterations == result.metrics.generated_columns == 0
    assert result.metrics.lp_pool_size is result.metrics.integer_pool_size is None
    assert result.metrics.master_solve_time_s == result.metrics.pricing_solve_time_s == 0
    assert result.metrics.pool_calls == result.metrics.greedy_pricing_calls == 0
    assert result.diagnostics.lp_convergence_proven
    assert result.diagnostics.cg_stop_reason == "empty_domain"
    assert result.diagnostics.convergence_basis == "empty_domain"
    assert result.diagnostics.pricing_objective is None
    assert result.diagnostics.pricing_best_bound is None
    assert result.diagnostics.interrupted_phase is None
    assert result.diagnostics.active_phase is None
    for name in ("initial_lp", "lp", "pricing", "pricing_phase2",
                 "auxiliary_pricing", "auxiliary_pricing_phase2", "integer_master"):
        assert getattr(result.diagnostics, name + "_status") == SolverPhaseStatus()
    assert result.iterations == []
    assert result.current_iteration is None


@pytest.mark.parametrize("dimensions", NO_FIT_CASES)
@pytest.mark.parametrize("return_mode", ["objective", "solution", "structured"])
@pytest.mark.parametrize("options", OPTIONS, ids=["defaults", "heuristics-and-mixed"])
def test_no_orientation_returns_zero_before_initialization_or_cplex(
    monkeypatch, dimensions, return_mode, options
):
    def forbidden(*args, **kwargs):
        pytest.fail("Empty geometry must be detected before initialization or CPLEX")

    monkeypatch.setattr(cplex, "Cplex", forbidden)
    monkeypatch.setattr(NormalizedProblem, "slice_height", property(forbidden))
    monkeypatch.setattr(cg, "generate_positions_xym", forbidden)
    monkeypatch.setattr(cg, "generate_initial_slices", forbidden)
    export = Mock()
    monkeypatch.setattr(cg, "export_final_layout", export)
    queue = Queue()
    result = cg.orchestrator(
        queue, None, 5, time.perf_counter(), ConfigData(*dimensions),
        return_solution=return_mode == "solution",
        return_structured=return_mode == "structured", **options,
    )
    if return_mode == "structured":
        assert_empty_certificate(result)
        messages = list(queue.queue)
        assert messages[-1]["finished"] is True
        assert_empty_certificate(messages[-1]["result"])
    elif return_mode == "solution":
        assert result == (0, [])
    else:
        assert result == 0
    export.assert_not_called()


@pytest.mark.parametrize("dimensions", NO_FIT_CASES)
def test_empty_certificate_survives_public_spawn_api(monkeypatch, dimensions):
    monkeypatch.setattr(cg, "multiprocessing", get_context("spawn"))
    instance = dict(zip(
        ("bin_width", "bin_height", "item_width", "item_height"), dimensions
    ), case_name="empty_domain_spawn")
    result = cg.execute_with_time_limit(10, instance, **OPTIONS[1])
    assert_empty_certificate(result)


@pytest.mark.parametrize("field", ["bin_width", "bin_height", "item_width", "item_height"])
@pytest.mark.parametrize("value", [None, True, 1.5, "1", 0, -1])
def test_invalid_dimensions_do_not_become_zero_certificates(field, value):
    config = ConfigData(5, 5, 6, 1)
    # Bypass ConfigData setters to exercise the orchestrator's preflight itself.
    setattr(config, "_" + field, value)
    result = cg.orchestrator(Queue(), None, 5, time.perf_counter(), config,
                             return_structured=True)
    assert result.execution.termination_status == PAVER.TERMINATION_ERROR
    assert result.execution.objective_value is None
    assert result.metrics.lp_value is None
    assert result.metrics.restricted_integer_master is None
    assert not result.diagnostics.lp_convergence_proven


@pytest.mark.parametrize("milp", [False, True], ids=["LP", "MILP"])
def test_empty_pricing_uses_its_actual_problem_type(milp):
    model = slave_problem.create_slave_model(5, set(), set(), {"pi": {}}, 5, 3, 3, 2, 3)
    try:
        for stream in ("results", "log", "warning", "error"):
            getattr(model, "set_" + stream + "_stream")(None)
        if milp:
            model.set_problem_type(model.problem_type.MILP)
        queue = Queue()
        result = slave_problem.solve_slave_model(
            model, queue, None, 5, 3, 3, 3, use_pricing_second_phase=False
        )
        assert result == (None, 0, [])
        message = next(message for message in list(queue.queue) if "state" in message)
        assert message["raw_status"] == (101 if milp else 1)
        assert message["state"].model_status == PAVER.MODEL_STATUS_OPTIMAL
        assert message["state"].termination_status == PAVER.TERMINATION_NORMAL
        assert message["objective"] == message["best_bound"] == 0
    finally:
        model.end()


@pytest.mark.parametrize("problem_type,raw", [(0, 999), (1, 999), (1, 1), (0, 101)])
def test_pricing_unknown_or_mismatched_status_is_still_an_error(problem_type, raw):
    model = Mock()
    model.get_problem_type.return_value = problem_type
    model.solution.get_status.return_value = raw
    model.solution.is_primal_feasible.return_value = True
    queue = Queue()
    assert not slave_problem.SlaveSolver._report_status(model, queue)
    message = queue.get_nowait()
    assert message["state"].termination_status == PAVER.TERMINATION_ERROR
    assert message["objective"] is message["best_bound"] is None
    model.solution.get_objective_value.assert_not_called()
    model.solution.MIP.get_best_objective.assert_not_called()
