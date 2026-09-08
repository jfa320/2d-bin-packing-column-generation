from queue import Queue, Empty
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from models.column_generation import column_generation_solver as cg
from models.column_generation import master_problem, slave_problem
from objects import Item, Slice
from objects.ConfigData import ConfigData
from utils.status_normalizer import map_cplex_lp_status, map_cplex_mip_status


def make_slice(x):
    return Slice(height=1, width=4, items=[
        Item(height=1, width=1, rotated=False, position_x=x, position_y=0)])


@pytest.fixture
def stub_run(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(cg.time, "perf_counter", lambda: clock[0])
    monkeypatch.setattr(cg, "generate_positions_xym2", lambda *args: ([], []))
    seed = make_slice(0)
    monkeypatch.setattr(cg, "generate_initial_slices", lambda *args: [seed])
    monkeypatch.setattr(cg, "export_final_layout", lambda *args: None)

    def build(*args):
        clock[0] += 1
        return object()

    monkeypatch.setattr(cg, "create_master_model", build)
    monkeypatch.setattr(cg, "create_slave_model", build)
    lp_values = iter([1.5, 2.5, 3.5])

    def master(model, queue, manual, relaxed, initial):
        clock[0] += 2
        value = next(lp_values) if relaxed else 2
        queue.put({"phase": "lp" if relaxed else "ip", "objective": value,
                   "state": map_cplex_lp_status(1) if relaxed else map_cplex_mip_status(101),
                   "raw_status": 1 if relaxed else 101})
        return value, {"pi": {}} if relaxed else None, []

    monkeypatch.setattr(cg, "solve_master_model", master)

    def run(pricing, **kwargs):
        responses = iter(pricing)

        def slave(model, queue, manual, *args, finalization_heuristics=None):
            clock[0] += 2
            queue.put({"phase": "pricing", "raw_status": 101,
                       "state": map_cplex_mip_status(101)})
            return next(responses)

        monkeypatch.setattr(cg, "solve_slave_model", slave)
        return cg.orchestrator(Queue(), SimpleNamespace(value=True), 60, 0,
                               ConfigData(4, 4, 1, 1), return_structured=True,
                               finalization_heuristics=False, **kwargs)

    return run


def test_completed_iterations_and_phase_metrics(stub_run):
    result = stub_run([(make_slice(1), 1, ["z_x_1_0"]), (None, 0, [])])
    assert result.metrics.cg_iterations == 2
    assert result.metrics.generated_columns == 1
    assert result.metrics.lp_value == 2.5
    assert result.metrics.restricted_integer_master == 2
    assert result.metrics.cg_time_s == 12
    assert result.metrics.integer_master_time_s == 3
    assert result.execution.total_time_s == 15
    assert result.execution.objective_value == 2
    assert result.execution.model_status == 8
    assert result.execution.termination_status == "Normal"


def test_seed_duplicate_not_counted(stub_run, monkeypatch):
    monkeypatch.setattr(cg, "USE_PRACTICAL_CG_ENHANCEMENTS", True)
    result = stub_run([(make_slice(0), 1, ["z_x_0_0"])])
    assert result.metrics.generated_columns == 0
    assert result.metrics.cg_iterations == 1
    assert result.execution.termination_status == "Normal"
    assert cg.USE_PRACTICAL_CG_ENHANCEMENTS is True


def test_explicit_false_disables_dual_stabilization(stub_run, monkeypatch):
    stabilize = Mock(side_effect=AssertionError("Stabilization must be disabled"))
    monkeypatch.setattr(cg, "stabilize_duals", stabilize)
    result = stub_run([(None, 0, [])])
    assert result.execution.termination_status == "Normal"
    stabilize.assert_not_called()


def test_failed_pricing_is_not_completed_iteration(stub_run):
    result = stub_run([(None, None, [])])
    assert result.metrics.cg_iterations == 0
    assert result.metrics.generated_columns == 0


def test_error_keeps_last_lp_not_integer(stub_run):
    result = stub_run([])
    assert result.execution.termination_status == "Error"
    assert result.metrics.lp_value == 1.5
    assert result.execution.objective_value is None
    assert result.metrics.restricted_integer_master is None


def test_abnormal_pricing_survives_final_master():
    progress = cg._CGProgress(Queue(), "stub", cg.time.perf_counter(), True)
    progress.put({"phase": "pricing", "state": map_cplex_mip_status(105), "raw_status": 105})
    progress.put({"phase": "ip", "state": map_cplex_mip_status(101),
                  "raw_status": 101, "objective": 3})
    result = progress.result()
    assert result.execution.termination_status == "NodeLimit"
    assert result.execution.raw_cplex_status == 105
    assert result.execution.model_status == 8


def test_failed_lp_retains_last_valid_lp():
    progress = cg._CGProgress(Queue(), "stub", cg.time.perf_counter(), True)
    progress.put({"phase": "lp", "state": map_cplex_lp_status(1),
                  "raw_status": 1, "objective": 2.5})
    progress.put({"phase": "lp", "state": map_cplex_lp_status(11, False),
                  "raw_status": 11, "objective": None})
    progress.put({"phase": "ip", "state": map_cplex_mip_status(101),
                  "raw_status": 101, "objective": 2})
    result = progress.result()
    assert result.metrics.lp_value == 2.5
    assert result.execution.objective_value == 2
    assert result.execution.termination_status == "TimeLimit"


@pytest.mark.parametrize("raw", [6, 10, 11, 12, 13])
def test_nonoptimal_feasible_lp_has_no_duals_or_lp_metric(raw, monkeypatch):
    progress = cg._CGProgress(Queue(), "stub", cg.time.perf_counter(), True)
    progress.put({"phase": "lp", "state": map_cplex_lp_status(1),
                  "raw_status": 1, "objective": 2.5})
    model = Mock()
    model.solution.get_status.return_value = raw
    model.solution.is_primal_feasible.return_value = True
    model.solution.get_objective_value.return_value = 3.5
    model.solution.get_values.return_value = []
    model.variables.get_names.return_value = []
    duals = Mock(side_effect=AssertionError("Invalid duals"))
    monkeypatch.setattr(master_problem, "get_dual_values", duals)
    _, dual_values, _ = master_problem.solve_master_model(model, progress, None, True, 0)
    assert dual_values is None
    duals.assert_not_called()
    assert progress.result().metrics.lp_value == 2.5
    assert progress.result().execution.termination_status != "Normal"


@pytest.mark.parametrize("phase,raw", [("lp", 5), ("ip", 115), ("pricing", 115)])
def test_numerically_invalid_optimum_is_not_a_valid_objective(phase, raw):
    progress = cg._CGProgress(Queue(), "stub", cg.time.perf_counter(), True)
    mapper = map_cplex_lp_status if phase == "lp" else map_cplex_mip_status
    progress.put({"phase": phase, "state": mapper(raw, True),
                  "raw_status": raw, "objective": 99})
    result = progress.result()
    assert result.execution.termination_status == "Normal"
    assert result.execution.model_status == 6
    assert result.execution.objective_value is None
    assert result.metrics.lp_value is None


def test_numerical_error_overrides_earlier_limit():
    progress = cg._CGProgress(Queue(), "stub", cg.time.perf_counter(), True)
    progress.put({"phase": "pricing", "state": map_cplex_mip_status(105), "raw_status": 105})
    progress.put({"phase": "ip", "state": map_cplex_mip_status(116),
                  "raw_status": 116, "objective": 2})
    result = progress.result()
    assert result.execution.termination_status == "Error"
    assert result.execution.raw_cplex_status == 116
    assert result.execution.model_status == 8


@pytest.mark.parametrize("relaxed,raw", [(True, 3), (False, 108)])
def test_master_without_feasibility_never_queries_objective(relaxed, raw):
    model = Mock()
    model.solution.get_status.return_value = raw
    model.solution.is_primal_feasible.return_value = False
    result = master_problem.solve_master_model(model, Queue(), SimpleNamespace(value=True), relaxed, 0)
    assert result == (None, None, [])
    model.solution.get_objective_value.assert_not_called()


@pytest.mark.parametrize("relaxed,raw", [(True, 5), (False, 115), (False, 117)])
def test_master_invalid_point_ignores_reported_feasibility(relaxed, raw):
    model = Mock()
    model.solution.get_status.return_value = raw
    model.solution.is_primal_feasible.return_value = True
    assert master_problem.solve_master_model(model, Queue(), None, relaxed, 0) == (None, None, [])
    model.solution.get_objective_value.assert_not_called()


def test_pricing_infeasible_not_confused_with_feasible_string():
    model = Mock()
    model.solution.get_status.return_value = 103
    model.solution.is_primal_feasible.return_value = False
    assert slave_problem.solve_slave_model(model, Queue(), None, 4, 1, 1, 1) == (None, None, [])
    model.solution.get_objective_value.assert_not_called()


@pytest.mark.parametrize("raw", [115, 117, 999])
def test_invalid_pricing_never_queries_objective(raw):
    model = Mock()
    model.solution.get_status.return_value = raw
    model.solution.is_primal_feasible.return_value = True
    progress = cg._CGProgress(Queue(), "stub", cg.time.perf_counter(), True)
    assert slave_problem.solve_slave_model(model, progress, None, 4, 1, 1, 1) == (None, None, [])
    model.solution.get_objective_value.assert_not_called()
    if raw == 115:
        assert progress.result().execution.termination_status == "Normal"
        assert progress.result().execution.model_status == 6
    else:
        assert progress.result().execution.termination_status == "Error"


def test_nonoptimal_pricing_preserves_limit_and_feasible_column():
    model = Mock()
    model.solution.get_status.return_value = 107
    model.solution.is_primal_feasible.return_value = True
    model.solution.get_objective_value.return_value = 1
    model.solution.get_values.return_value = [1]
    model.variables.get_names.return_value = ["z_x_0_0"]
    model.objective.get_linear.return_value = [1]
    progress = cg._CGProgress(Queue(), "stub", cg.time.perf_counter(), True)
    column, value, _ = slave_problem.solve_slave_model(
        model, progress, None, 4, 1, 1, 1, finalization_heuristics=False)
    assert column is not None
    assert value == 1
    assert progress.result().execution.termination_status == "TimeLimit"
    assert progress.result().execution.objective_value is None


def test_explicit_false_disables_pricing_phase_without_global_change(monkeypatch):
    monkeypatch.setattr(slave_problem, "USE_PRACTICAL_CG_ENHANCEMENTS", True)
    model = Mock()
    model.solution.get_status.return_value = 101
    model.solution.is_primal_feasible.return_value = True
    model.solution.get_objective_value.return_value = 1
    model.solution.get_values.return_value = [1]
    model.variables.get_names.return_value = ["z_x_0_0"]
    model.objective.get_linear.return_value = [1]
    slave_problem.solve_slave_model(model, Queue(), None, 4, 1, 1, 1, finalization_heuristics=False)
    assert model.solve.call_count == 1
    assert slave_problem.USE_PRACTICAL_CG_ENHANCEMENTS is True


@pytest.mark.parametrize("incumbent", [None, 2])
def test_parent_deadline_drains_partial_results(monkeypatch, incumbent):
    clock = [0.0]
    monkeypatch.setattr(cg.time, "perf_counter", lambda: clock[0])
    progress = cg._CGProgress(Queue(), "stub", 0, True)
    progress.metrics = cg.ColumnGenerationMetrics(lp_value=2.5, restricted_integer_master=incumbent,
                                               cg_iterations=3, generated_columns=2)
    snapshot = progress.result()

    class StubQueue:
        sent = False

        def get(self, timeout):
            clock[0] += timeout
            if not self.sent:
                self.sent = True
                return snapshot
            raise Empty

        def close(self):
            pass

    process = Mock()
    process.is_alive.return_value = True
    monkeypatch.setattr(cg.multiprocessing, "Queue", StubQueue)
    monkeypatch.setattr(cg.multiprocessing, "Process", lambda **kwargs: process)
    result = cg.execute_with_time_limit(0.2, {"case_name": "stub", "bin_width": 4,
        "bin_height": 4, "item_width": 1, "item_height": 1}, finalization_heuristics=False)
    assert result.execution.termination_status == "TimeLimit"
    assert result.execution.objective_value == incumbent
    assert result.metrics.lp_value == 2.5
    assert result.metrics.cg_iterations == 3
    assert result.execution.total_time_s >= 0.2
    process.terminate.assert_called()


def test_parent_queue_creation_failure_is_structured(monkeypatch):
    monkeypatch.setattr(cg.multiprocessing, "Queue", Mock(side_effect=OSError("queue unavailable")))
    result = cg.execute_with_time_limit(1, {"case_name": "stub"})
    assert result.execution.termination_status == "Error"
    assert result.execution.error_message == "queue unavailable"
    assert result.execution.objective_value is None


def test_child_exception_before_first_solve_is_reported(monkeypatch):
    monkeypatch.setattr(cg, "generate_positions_xym2", Mock(side_effect=ValueError("bad positions")))
    queue = Queue()
    result = cg.orchestrator(queue, None, 1, 0, ConfigData(4, 4, 1, 1), return_structured=True)
    assert result.execution.termination_status == "Error"
    assert result.execution.error_message == "bad positions"
    assert result.execution.objective_value is None
    assert result.metrics.cg_iterations == 0
    assert queue.get_nowait().execution.termination_status == "Error"
    assert queue.get_nowait()["finished"] is True


@pytest.mark.parametrize("completed", [False, True])
def test_parent_requires_completion_not_just_snapshot(monkeypatch, completed):
    queue = Queue()
    snapshot = cg._CGProgress(queue, "stub", cg.time.perf_counter(), True).result()
    queue.put(snapshot)
    if completed:
        queue.put({"result": snapshot, "finished": True})
    queue.close = Mock()
    process = Mock()
    process.is_alive.return_value = False
    process.exitcode = 0
    monkeypatch.setattr(cg.multiprocessing, "Queue", lambda: queue)
    monkeypatch.setattr(cg.multiprocessing, "Process", lambda **kwargs: process)
    result = cg.execute_with_time_limit(10, {"case_name": "stub", "bin_width": 4,
        "bin_height": 4, "item_width": 1, "item_height": 1})
    assert result.execution.termination_status == ("Normal" if completed else "Error")


def test_phase_times_are_not_rounded(monkeypatch):
    monkeypatch.setattr(cg.time, "perf_counter", lambda: 1.123456789)
    progress = cg._CGProgress(Queue(), "stub", 1.0, True)
    result = progress.result()
    assert result.execution.total_time_s == 1.123456789 - 1.0
    assert result.metrics.cg_time_s == result.execution.total_time_s
