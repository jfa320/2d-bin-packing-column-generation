import importlib
import time
from dataclasses import asdict
from unittest.mock import Mock

import pytest

from utils.execution_result import (
    ColumnGenerationExecutionResult,
    ColumnGenerationMetrics,
    ExecutionResult,
)
from utils.execution_runner import execute_in_process
from utils.status_normalizer import map_cplex_lp_status, map_cplex_mip_status


@pytest.mark.parametrize("raw,model,termination,feasible", [
    (101, 1, "Normal", True),
    (102, 8, "Normal", True),
    (103, 10, "Normal", False),
    (104, 8, "OtherLimit", True),
    (105, 8, "NodeLimit", True),
    (106, 9, "NodeLimit", False),
    (107, 8, "TimeLimit", True),
    (108, 9, "TimeLimit", False),
    (109, 8, "Error", True),
    (110, 13, "Error", False),
    (111, 8, "OtherLimit", True),
    (112, 9, "OtherLimit", False),
    (113, 8, "Other", True),
    (114, 9, "Other", False),
    (115, 6, "Normal", False),
    (116, 8, "Error", True),
    (117, 13, "Error", False),
    (118, 18, "Normal", False),
    (119, 12, "Normal", False),
    (127, 8, "Other", True),
    (131, 8, "TimeLimit", True),
    (132, 9, "TimeLimit", False),
    (133, 13, "Other", False),
])
def test_mip_statuses(raw, model, termination, feasible):
    status = map_cplex_mip_status(raw)
    assert (status.model_status, status.termination_status, status.has_feasible_solution) == (
        model, termination, feasible,
    )


@pytest.mark.parametrize("raw,model,termination,feasible", [
    (1, 1, "Normal", True),
    (2, 18, "Normal", False),
    (3, 4, "Normal", False),
    (4, 12, "Normal", False),
    (5, 6, "Normal", False),
    (6, 6, "Other", False),
    (10, 6, "IterationLimit", False),
    (11, 6, "TimeLimit", False),
    (12, 6, "OtherLimit", False),
    (13, 6, "UserInterrupt", False),
])
def test_lp_statuses(raw, model, termination, feasible):
    status = map_cplex_lp_status(raw)
    assert (status.model_status, status.termination_status, status.has_feasible_solution) == (
        model, termination, feasible,
    )


@pytest.mark.parametrize("mapper", [map_cplex_mip_status, map_cplex_lp_status])
@pytest.mark.parametrize("raw", [None, 0, -1, 999, "101"])
def test_unknown_status_is_conservative(mapper, raw):
    status = mapper(raw, has_feasible_solution=True)
    assert status.model_status == 13
    assert status.termination_status == "Error"
    assert not status.has_feasible_solution


@pytest.mark.parametrize("raw,expected", [
    (101, 13), (102, 13), (104, 9), (105, 9), (107, 9),
    (109, 13), (111, 9), (113, 9), (116, 13), (127, 9), (131, 9),
])
def test_mip_primal_query_overrides_implied_incumbent(raw, expected):
    status = map_cplex_mip_status(raw, False)
    assert status.model_status == expected
    assert not status.has_feasible_solution


@pytest.mark.parametrize("raw,termination", [
    (6, "Other"), (10, "IterationLimit"), (11, "TimeLimit"),
    (12, "OtherLimit"), (13, "UserInterrupt"),
])
@pytest.mark.parametrize("feasible", [True, False])
def test_lp_primal_query_controls_intermediate_status(raw, termination, feasible):
    status = map_cplex_lp_status(raw, feasible)
    assert (status.model_status, status.termination_status, status.has_feasible_solution) == (
        7 if feasible else 6, termination, feasible,
    )


@pytest.mark.parametrize("mapper,raw", [(map_cplex_mip_status, 115), (map_cplex_lp_status, 5)])
def test_invalid_optimal_point_never_authorizes_objective(mapper, raw):
    assert not mapper(raw, True).has_feasible_solution


@pytest.mark.parametrize("raw,model,termination", [
    (103, 10, "Normal"), (110, 13, "Error"), (115, 6, "Normal"),
    (117, 13, "Error"), (118, 18, "Normal"), (119, 12, "Normal"),
    (133, 13, "Other"),
])
@pytest.mark.parametrize("feasible", [None, False, True])
def test_fixed_mip_statuses_reject_primal_override(raw, model, termination, feasible):
    status = map_cplex_mip_status(raw, feasible)
    assert (status.model_status, status.termination_status, status.has_feasible_solution) == (
        model, termination, False,
    )


@pytest.mark.parametrize("feasible", [False, True])
def test_mip_solution_limit_uses_incumbent(feasible):
    status = map_cplex_mip_status(104, feasible)
    assert (status.model_status, status.termination_status, status.has_feasible_solution) == (
        8 if feasible else 9, "OtherLimit", feasible,
    )


@pytest.mark.parametrize("mapper,raw,termination", [
    (map_cplex_mip_status, 113, "Other"), (map_cplex_mip_status, 114, "Other"),
    (map_cplex_lp_status, 13, "UserInterrupt"),
])
def test_explicit_user_interruption(mapper, raw, termination):
    assert mapper(raw).termination_status == termination
    assert mapper(raw, user_interrupted=True).termination_status == "UserInterrupt"


def test_result_contract():
    result = ExecutionResult("case", "model", 9, "TimeLimit", None, 1.0)
    assert list(asdict(result)) == [
        "case_name", "model_name", "model_status", "termination_status",
        "objective_value", "total_time_s", "raw_cplex_status", "error_message",
    ]
    metrics = ColumnGenerationMetrics()
    assert asdict(metrics) == dict(
        lp_value=None, restricted_integer_master=None, cg_iterations=0,
        generated_columns=0, cg_time_s=0.0, integer_master_time_s=0.0,
    )
    assert ColumnGenerationExecutionResult(result, metrics).execution is result


def _worker_success(queue, max_time, instance):
    queue.put(ExecutionResult(instance["case_name"], "worker", 1, "Normal", 0.0, 0.0))


def _worker_slow(queue, max_time, instance):
    time.sleep(30)


def _worker_large_message(queue, max_time, instance):
    queue.put(ExecutionResult(
        instance["case_name"], "worker", None, "Error", None, 0.0,
        error_message="x" * 1_000_000,
    ))


def _worker_no_result(queue, max_time, instance):
    pass


def test_runner_success_includes_setup_time():
    start = time.perf_counter() - 0.2
    result = execute_in_process(_worker_success, 10, {"case_name": "test"}, "parent", start)
    assert (result.case_name, result.model_name, result.model_status) == ("test", "parent", 1)
    assert result.objective_value == 0.0
    assert result.total_time_s >= 0.2


@pytest.mark.parametrize("worker,budget,objective,model_status", [
    (_worker_slow, 0, None, 9),
    (_worker_slow, 0.2, None, 9),
])
def test_runner_deadline(worker, budget, objective, model_status):
    result = execute_in_process(worker, budget, {"case_name": "test"}, "parent")
    assert result.termination_status == "TimeLimit"
    assert result.objective_value == objective
    assert result.model_status == model_status
    assert budget <= result.total_time_s < budget + 3


def _worker_incumbent_then_sleep(queue, max_time, instance):
    _worker_success(queue, max_time, instance)
    time.sleep(30)


def test_runner_preserves_recovered_incumbent_at_deadline():
    result = execute_in_process(_worker_incumbent_then_sleep, 2, {"case_name": "test"}, "parent")
    assert (result.model_status, result.termination_status, result.objective_value) == (8, "TimeLimit", 0.0)
    assert 2 <= result.total_time_s < 5


def test_runner_drains_large_message_before_join():
    result = execute_in_process(_worker_large_message, 10, {"case_name": "test"}, "parent")
    assert result.termination_status == "Error"
    assert result.error_message == "x" * 1_000_000


def test_runner_missing_result_is_error():
    result = execute_in_process(_worker_no_result, 10, {"case_name": "test"}, "parent")
    assert result.termination_status == "Error"
    assert result.objective_value is None
    assert "without a result" in result.error_message


def _worker_raises(queue, max_time, instance):
    raise ValueError("child setup failed")


def _worker_success_then_crash(queue, max_time, instance):
    import os

    _worker_success(queue, max_time, instance)
    os._exit(7)


@pytest.mark.parametrize("worker,error", [
    (_worker_raises, "ValueError: child setup failed"),
    (_worker_success_then_crash, "exit code 7"),
])
def test_runner_child_failure_is_explicit(worker, error):
    result = execute_in_process(worker, 10, {"case_name": "test"}, "parent")
    assert result.termination_status == "Error"
    assert error in result.error_message


def test_runner_start_failure_is_explicit(monkeypatch):
    from utils import execution_runner

    process = Mock(pid=None)
    process.start.side_effect = RuntimeError("start failed")
    monkeypatch.setattr(execution_runner.multiprocessing, "Process", Mock(return_value=process))
    result = execute_in_process(_worker_success, 10, {"case_name": "test"}, "parent")
    assert result.termination_status == "Error"
    assert "start failed" in result.error_message
    process.join.assert_not_called()
    process.close.assert_called_once_with()


@pytest.mark.parametrize("raw,feasible,expected", [
    (105, True, 2.0), (108, False, None), (115, True, None),
    (101, False, None), (999, True, None),
])
def test_objective_is_only_queried_when_valid(raw, feasible, expected):
    pytest.importorskip("cplex")
    from utils.model_functions import solve_mip_model

    model = Mock()
    model.solution.get_status.return_value = raw
    model.solution.is_primal_feasible.return_value = feasible
    model.solution.get_objective_value.return_value = 2
    result = solve_mip_model(model, "case", "model")
    assert result.objective_value == expected
    assert result.raw_cplex_status == raw
    model.solution.is_primal_feasible.assert_called_once_with()
    assert model.solution.get_objective_value.call_count == int(expected is not None)


def test_creation_error_returns_typed_error():
    pytest.importorskip("cplex")
    from utils.model_functions import run_model

    queue = Mock()
    run_model(Mock(side_effect=ValueError("bad setup")), Mock(), queue, 1, "case", "model")
    result = queue.put.call_args.args[0]
    assert isinstance(result, ExecutionResult)
    assert result.termination_status == "Error"
    assert result.objective_value is None
    assert result.error_message == "bad setup"


def test_cleanup_error_still_publishes_result():
    pytest.importorskip("cplex")
    from utils.model_functions import run_model

    model = Mock()
    model.end.side_effect = RuntimeError("cleanup failed")
    queue = Mock()
    run_model(
        Mock(return_value=model),
        Mock(return_value=ExecutionResult("case", "model", 1, "Normal", 4.0, 0.0)),
        queue, 1, "case", "model",
    )
    result = queue.put.call_args.args[0]
    assert result.termination_status == "Error"
    assert result.error_message == "Model cleanup failed: cleanup failed"


def test_parent_user_interruption(monkeypatch):
    from utils import execution_runner

    monkeypatch.setattr(execution_runner.multiprocessing, "Pipe", Mock(side_effect=KeyboardInterrupt))
    result = execute_in_process(_worker_success, 10, {"case_name": "test"}, "parent")
    assert (result.model_status, result.termination_status, result.objective_value) == (9, "UserInterrupt", None)


COMPARATIVE_MODULES = [
    "Model_1_Simplified_Section_2_8_No_Rotation",
    "Model_1_Simplified_Section_2_9_With_Rotation",
    "Model_6_Andrade_Birgin_Monoitem",
    "Model_7_Exact_Monoitem_Backtracking",
]


@pytest.mark.parametrize("module_name", COMPARATIVE_MODULES)
def test_comparative_public_contract(module_name):
    if "Backtracking" not in module_name:
        pytest.importorskip("cplex")
    module = importlib.import_module("models.comparative." + module_name)
    instance = dict(case_name="tiny", bin_width=2, bin_height=2, item_width=1, item_height=1)
    result = module.execute_with_time_limit(10, instance)
    assert isinstance(result, ExecutionResult)
    assert result.case_name == "tiny"
    assert result.model_name == module.MODEL_NAME
    assert result.model_status == 1
    assert result.termination_status == "Normal"
    assert result.objective_value == 4.0
    assert 0 < result.total_time_s < 10
    timeout = module.execute_with_time_limit(0, instance)
    assert (timeout.model_status, timeout.termination_status, timeout.objective_value) == (9, "TimeLimit", None)


def test_model_names_are_unique():
    pytest.importorskip("cplex")
    names = [importlib.import_module("models.comparative." + name).MODEL_NAME for name in COMPARATIVE_MODULES]
    assert len(set(names)) == len(names)
    assert names[:2] == ["Model1NoRotation", "Model1Rotation"]


@pytest.mark.parametrize("raw", [109, 110, 116, 117, 999])
def test_solver_error_status_has_diagnostic(raw):
    pytest.importorskip("cplex")
    from utils.model_functions import solve_mip_model

    model = Mock()
    model.solution.get_status.return_value = raw
    model.solution.is_primal_feasible.return_value = False
    result = solve_mip_model(model, "case", "model")
    assert result.termination_status == "Error"
    assert str(raw) in result.error_message


def test_solve_and_cleanup_errors_are_both_preserved():
    pytest.importorskip("cplex")
    from utils.model_functions import run_model

    model = Mock()
    model.end.side_effect = RuntimeError("cleanup failed")
    queue = Mock()
    run_model(Mock(return_value=model), Mock(side_effect=ValueError("solve failed")),
              queue, 1, "case", "model")
    result = queue.put.call_args.args[0]
    assert "solve failed" in result.error_message
    assert "cleanup failed" in result.error_message


def test_total_time_is_not_rounded(monkeypatch):
    from utils import execution_runner

    monkeypatch.setattr(execution_runner, "perf_counter", Mock(side_effect=[1.0, 1.0, 1.123456789]))
    result = execute_in_process(_worker_success, 0, {"case_name": "test"}, "parent")
    assert result.total_time_s == 1.123456789 - 1.0


def test_blocked_ipc_read_cannot_block_parent_deadline(monkeypatch):
    from threading import Event
    from utils import execution_runner

    release = Event()
    stopped = Event()

    def blocked_recv():
        release.wait(5)
        raise EOFError

    reader = Mock()
    reader.recv.side_effect = blocked_recv
    reader.close.side_effect = stopped.set
    process = Mock(pid=123, exitcode=0)
    process.is_alive.return_value = False
    monkeypatch.setattr(execution_runner.multiprocessing, "Pipe", Mock(return_value=(reader, Mock())))
    monkeypatch.setattr(execution_runner.multiprocessing, "Process", Mock(return_value=process))
    try:
        result = execute_in_process(_worker_success, 0.2, {"case_name": "test"}, "parent")
        assert result.termination_status == "TimeLimit"
        assert 0.2 <= result.total_time_s < 1
        assert "receiver did not stop" in result.error_message
    finally:
        release.set()
        assert stopped.wait(2)


def test_parent_cleanup_failure_is_returned(monkeypatch):
    from utils import execution_runner

    process = Mock(pid=None)
    process.start.side_effect = RuntimeError("start failed")
    process.close.side_effect = RuntimeError("close failed")
    monkeypatch.setattr(execution_runner.multiprocessing, "Process", Mock(return_value=process))
    result = execute_in_process(_worker_success, 10, {"case_name": "test"}, "parent")
    assert result.termination_status == "Error"
    assert "start failed" in result.error_message
    assert "close failed" in result.error_message


def test_receiver_start_failure_is_returned(monkeypatch):
    from utils import execution_runner

    receiver = Mock(ident=None)
    receiver.start.side_effect = RuntimeError("receiver start failed")
    monkeypatch.setattr(execution_runner, "Thread", Mock(return_value=receiver))
    result = execute_in_process(_worker_slow, 10, {"case_name": "test"}, "parent")
    assert result.termination_status == "Error"
    assert "receiver start failed" in result.error_message
    receiver.join.assert_not_called()


@pytest.mark.parametrize("raw,model", [(2, 18), (3, 4), (4, 12), (5, 6)])
@pytest.mark.parametrize("feasible", [None, False, True])
def test_fixed_lp_statuses_reject_primal_override(raw, model, feasible):
    status = map_cplex_lp_status(raw, feasible)
    assert (status.model_status, status.termination_status, status.has_feasible_solution) == (
        model, "Normal", False,
    )


def test_model_creation_consumes_solver_budget(monkeypatch):
    pytest.importorskip("cplex")
    from utils import model_functions

    monkeypatch.setattr(model_functions.time, "perf_counter", Mock(side_effect=[1.0, 3.0, 3.123456]))
    model = Mock()
    solve = Mock()
    queue = Mock()
    model_functions.run_model(Mock(return_value=model), solve, queue, 1, "case", "model")
    result = queue.put.call_args.args[0]
    assert result.termination_status == "TimeLimit"
    assert result.total_time_s == 3.123456 - 1.0
    solve.assert_not_called()
    model.end.assert_called_once_with()
