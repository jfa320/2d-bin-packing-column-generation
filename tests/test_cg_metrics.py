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
    monkeypatch.setattr(cg, "generate_positions_xym", lambda *args: ([], []))
    seed = make_slice(0)
    monkeypatch.setattr(cg, "generate_initial_slices", lambda *args: [seed])
    monkeypatch.setattr(cg, "export_final_layout", lambda *args: None)
    monkeypatch.setattr(cg, "add_no_good_cut", lambda *args: None)
    monkeypatch.setattr(cg, "add_non_empty_constraint", lambda *args: None)
    master_builds = []
    incremental_updates = []
    pricing_models = []

    def build_master(*args):
        clock[0] += 1
        master_builds.append(args[1])
        return object()

    def build_slave(*args):
        clock[0] += 1
        return object()

    class IncrementalMasterStub:
        def __init__(self, model, slices, height_bin, width_bin):
            self.model = model
            self.slice_ids = {slice_.get_id() for slice_ in slices}

        def add_slice(self, slice_):
            incremental_updates.append(slice_.get_id())
            self.slice_ids.add(slice_.get_id())
            return True

    monkeypatch.setattr(cg, "create_master_model", build_master)
    monkeypatch.setattr(cg, "create_slave_model", build_slave)
    monkeypatch.setattr(cg, "IncrementalMasterModel", IncrementalMasterStub)
    lp_values = iter([1.5, 2.5, 3.5])

    def master(model, queue, manual, relaxed, initial):
        with cg.timed_component(queue, "master_solve"):
            clock[0] += 2
        value = next(lp_values) if relaxed else 2
        queue.put({"phase": "lp" if relaxed else "ip", "objective": value,
                   "state": map_cplex_lp_status(1) if relaxed else map_cplex_mip_status(101),
                   "raw_status": 1 if relaxed else 101})
        return value, {"pi": {}} if relaxed else None, []

    monkeypatch.setattr(cg, "solve_master_model", master)

    def run(pricing, pricing_raw_status=101, pricing_best_bound=None, **kwargs):
        responses = iter(pricing)

        def slave(model, queue, manual, *args, finalization_heuristics=None):
            pricing_models.append(model)
            with cg.timed_component(queue, "pricing_solve"):
                clock[0] += 2
                response = next(responses)
            queue.put({"phase": "pricing", "raw_status": pricing_raw_status,
                       "state": map_cplex_mip_status(pricing_raw_status),
                       "objective": response[1], "best_bound": (
                           response[1] if pricing_raw_status == 101 else pricing_best_bound)})
            return response

        monkeypatch.setattr(cg, "solve_slave_model", slave)
        return cg.orchestrator(Queue(), SimpleNamespace(value=True), 60, 0,
                               ConfigData(4, 4, 1, 1), return_structured=True,
                               finalization_heuristics=kwargs.pop("finalization_heuristics", False),
                               # Existing timing fixtures exercise the rebuild baseline.
                               pricing_mode=kwargs.pop("pricing_mode", "rebuild"), **kwargs)

    run.master_builds = master_builds
    run.incremental_updates = incremental_updates
    run.clock = clock
    run.pricing_models = pricing_models
    return run


def test_completed_iterations_and_phase_metrics(stub_run):
    result = stub_run([(make_slice(1), 1, ["z_x_1_0"]), (None, 0, [])])
    assert result.metrics.cg_iterations == 2
    assert result.metrics.generated_columns == 1
    assert result.metrics.lp_value == 2.5
    assert result.metrics.restricted_integer_master == 2
    assert result.metrics.cg_time_s == 11
    assert result.metrics.integer_master_time_s == 3
    assert result.metrics.master_lp_time_s == 5
    assert result.metrics.pricing_time_s == 6
    assert result.diagnostics.cg_stop_reason == "pricing_converged"
    assert result.diagnostics.lp_convergence_proven
    assert result.diagnostics.convergence_basis == "optimal_pricing"
    assert result.diagnostics.lp_status.raw_cplex_status == 1
    assert result.diagnostics.pricing_status.raw_cplex_status == 101
    assert result.diagnostics.integer_master_status.model_status == 1
    assert result.execution.total_time_s == 14
    assert result.execution.objective_value == 2
    assert result.execution.model_status == 8
    assert result.execution.termination_status == "Normal"
    assert len(stub_run.master_builds) == 2  # Initial LP master and final integer master.
    assert len(stub_run.incremental_updates) == 1


@pytest.mark.parametrize("pricing_mode", ["auto", "reuse"])
@pytest.mark.parametrize("global_enhancements", [False, True])
def test_reused_pricing_is_built_once_and_update_time_is_recorded(
        stub_run, monkeypatch, pricing_mode, global_enhancements):
    sessions = []

    class PricingSession:
        def __init__(self, *args):
            self.model = object()
            self.preparations = 0
            self.closes = 0
            sessions.append(self)

        def prepare(self, duals):
            stub_run.clock[0] += 1 if self.preparations == 0 else 0.25
            self.preparations += 1
            return self.model

        def close(self):
            self.closes += 1

    monkeypatch.setattr(cg, "IncrementalPricingModel", PricingSession)
    monkeypatch.setattr(cg, "USE_PRACTICAL_CG_ENHANCEMENTS", global_enhancements)
    result = stub_run([(make_slice(1), 1, ["z_x_1_0"]), (None, 0, [])],
                      pricing_mode=pricing_mode, finalization_heuristics=False)
    assert result.execution.termination_status == "Normal"
    assert len(sessions) == 1
    assert sessions[0].preparations == 2
    assert sessions[0].closes == 1
    assert stub_run.pricing_models == [sessions[0].model, sessions[0].model]
    assert result.metrics.pricing_build_time_s == 1.25
    assert result.metrics.pricing_solve_time_s == 4
    assert [row.pricing_build_time_s for row in result.iterations] == [1, 0.25]
    assert result.diagnostics.lp_convergence_proven


@pytest.mark.parametrize("pricing_mode", ["auto", "reuse"])
def test_reused_pricing_is_closed_after_preparation_failure(stub_run, monkeypatch, pricing_mode):
    closed = []

    class FailingSession:
        def __init__(self, *args):
            pass

        def prepare(self, duals):
            raise RuntimeError("cannot build pricing")

        def close(self):
            closed.append(True)

    monkeypatch.setattr(cg, "IncrementalPricingModel", FailingSession)
    result = stub_run([], pricing_mode=pricing_mode)
    assert result.execution.termination_status == "Error"
    assert "cannot build pricing" in result.execution.error_message
    assert closed == [True]


@pytest.mark.parametrize("heuristics,global_flag", [(True, False), (None, True)])
def test_auto_keeps_rebuilding_when_enhancements_are_enabled(
        stub_run, monkeypatch, heuristics, global_flag):
    session = Mock(side_effect=AssertionError("Enhanced pricing must use fresh models"))
    monkeypatch.setattr(cg, "IncrementalPricingModel", session)
    monkeypatch.setattr(cg, "USE_PRACTICAL_CG_ENHANCEMENTS", global_flag)
    result = stub_run([(None, None, [])], pricing_mode="auto", finalization_heuristics=heuristics)
    assert result.execution.termination_status == "Normal"
    assert len(stub_run.pricing_models) == 1
    session.assert_not_called()


@pytest.mark.parametrize("options,message", [
    ({"pricing_mode": "unknown"}, "Unknown pricing mode"),
    ({"pricing_mode": "reuse", "finalization_heuristics": True}, "only the base algorithm"),
])
def test_invalid_pricing_mode_is_reported_before_any_solve(stub_run, options, message):
    result = stub_run([], **options)
    assert result.execution.termination_status == "Error"
    assert message in result.execution.error_message
    assert stub_run.master_builds == []
    assert stub_run.pricing_models == []


def test_failed_incremental_update_rebuilds_master(stub_run, monkeypatch, capsys):
    original_build = cg.create_master_model
    original_solve = cg.solve_master_model
    incremental_stub = cg.IncrementalMasterModel
    builds = []
    relaxed_solves = []
    update_attempts = []

    def build(*args):
        original_build(*args)
        model = SimpleNamespace(partially_updated=False)
        builds.append((model, tuple(slice_.get_id() for slice_ in args[1])))
        return model

    def solve(model, queue, manual, relaxed, initial):
        if relaxed:
            relaxed_solves.append(model)
        return original_solve(model, queue, manual, relaxed, initial)

    class FailingOnce(incremental_stub):
        def add_slice(self, slice_):
            update_attempts.append(slice_.get_id())
            if len(update_attempts) == 1:
                self.model.partially_updated = True
                raise RuntimeError("simulated CPLEX mutation failure")
            return super().add_slice(slice_)

    monkeypatch.setattr(cg, "create_master_model", build)
    monkeypatch.setattr(cg, "solve_master_model", solve)
    monkeypatch.setattr(cg, "IncrementalMasterModel", FailingOnce)

    generated = make_slice(1)
    result = stub_run([(generated, 1, ["z_x_1_0"]), (None, 0, [])])

    assert result.execution.termination_status == "Normal"
    assert result.execution.objective_value == 2
    assert result.metrics.cg_iterations == 2
    assert result.metrics.generated_columns == 1
    assert result.metrics.master_lp_time_s == 6
    assert len(builds) == 3  # Initial LP, fallback LP, final integer master.
    assert builds[1][1] == builds[0][1] + (generated.get_id(),)
    assert relaxed_solves == [builds[0][0], builds[1][0]]
    assert builds[0][0].partially_updated
    assert not builds[1][0].partially_updated
    assert update_attempts == [generated.get_id()]
    assert stub_run.incremental_updates == []
    assert "simulated CPLEX mutation failure" in capsys.readouterr().out


def test_seed_duplicate_not_counted(stub_run, monkeypatch):
    monkeypatch.setattr(cg, "USE_PRACTICAL_CG_ENHANCEMENTS", True)
    result = stub_run([(make_slice(0), 1, ["z_x_0_0"])])
    assert result.metrics.generated_columns == 0
    assert result.metrics.cg_iterations == 1
    assert result.execution.termination_status == "Normal"
    assert cg.USE_PRACTICAL_CG_ENHANCEMENTS is True
    assert result.diagnostics.cg_stop_reason == "duplicate"
    assert not result.diagnostics.lp_convergence_proven


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
    assert result.diagnostics.cg_stop_reason == "pricing_no_solution"


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


def test_incremental_master_adds_column_and_new_cell_row():
    class Variables:
        type = SimpleNamespace(binary="B")

        def __init__(self):
            self.added = []

        def add(self, **kwargs):
            self.added.append(kwargs)

    class LinearConstraints:
        def __init__(self, names):
            self.names = list(names)
            self.added = []

        def get_names(self):
            return list(self.names)

        def add(self, **kwargs):
            self.added.append(kwargs)
            self.names.extend(kwargs["names"])

    seed = make_slice(0)
    generated = Slice(height=1, width=4, items=[
        Item(height=1, width=2, rotated=False, position_x=0, position_y=0)])
    model = SimpleNamespace(
        variables=Variables(),
        linear_constraints=LinearConstraints(["consItem_0_0"]),
    )
    incremental = master_problem.IncrementalMasterModel(
        model, [seed], height_bin=2, width_bin=4,
    )

    assert incremental.add_slice(generated)
    variable = model.variables.added[0]
    assert variable["names"] == [f"p_{generated.get_id()}"]
    assert variable["obj"] == [generated.get_total_items()]
    assert variable["ub"] == [1.0]
    assert variable["columns"][0].ind == ["consItem_0_0"]
    assert variable["columns"][0].val == [1.0]
    assert model.linear_constraints.added[0]["names"] == ["consItem_1_0"]
    assert model.linear_constraints.added[0]["lin_expr"][0].ind == [
        f"p_{generated.get_id()}"
    ]
    assert model.linear_constraints.added[0]["rhs"] == [1.0]
    assert not incremental.add_slice(generated)


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
    def shutdown_delay(*args):
        clock[0] += 1.0
    process.join.side_effect = shutdown_delay
    monkeypatch.setattr(cg.multiprocessing, "Queue", StubQueue)
    monkeypatch.setattr(cg.multiprocessing, "Process", lambda **kwargs: process)
    result = cg.execute_with_time_limit(0.2, {"case_name": "stub", "bin_width": 4,
        "bin_height": 4, "item_width": 1, "item_height": 1}, finalization_heuristics=False)
    assert result.execution.termination_status == "TimeLimit"
    assert result.execution.objective_value == incumbent
    assert result.metrics.lp_value == 2.5
    assert result.metrics.cg_iterations == 3
    assert result.execution.total_time_s >= 0.2
    assert result.metrics.cg_time_s == pytest.approx(0.2)
    assert result.diagnostics.interrupted_phase == "preparation"
    assert result.diagnostics.cg_stop_reason == "wall_clock_timeout"
    process.terminate.assert_called()


def test_parent_queue_creation_failure_is_structured(monkeypatch):
    monkeypatch.setattr(cg.multiprocessing, "Queue", Mock(side_effect=OSError("queue unavailable")))
    result = cg.execute_with_time_limit(1, {"case_name": "stub"})
    assert result.execution.termination_status == "Error"
    assert result.execution.error_message == "queue unavailable"
    assert result.execution.objective_value is None


def test_child_exception_before_first_solve_is_reported(monkeypatch):
    monkeypatch.setattr(cg, "generate_positions_xym", Mock(side_effect=ValueError("bad positions")))
    queue = Queue()
    result = cg.orchestrator(queue, None, 1, 0, ConfigData(4, 4, 1, 1), return_structured=True)
    assert result.execution.termination_status == "Error"
    assert result.execution.error_message == "bad positions"
    assert result.execution.objective_value is None
    assert result.metrics.cg_iterations == 0
    assert queue.get_nowait().diagnostics.active_phase == "preparation"
    assert queue.get_nowait().execution.termination_status == "Error"
    assert queue.get_nowait()["finished"] is True
    assert result.diagnostics.cg_stop_reason == "error"
    assert result.diagnostics.interrupted_phase == "preparation"


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


@pytest.mark.parametrize("bound,proven,reason", [
    (None, False, "pricing_limit"),
    (1.0, False, "pricing_limit"),
    (0.0, True, "pricing_converged"),
])
def test_nonpositive_limited_pricing_requires_a_bound(stub_run, bound, proven, reason):
    result = stub_run([(None, 0.0, [])], pricing_raw_status=107, pricing_best_bound=bound)
    assert result.diagnostics.lp_convergence_proven is proven
    assert result.diagnostics.cg_stop_reason == reason
    assert result.diagnostics.pricing_status.raw_cplex_status == 107
    assert result.diagnostics.integer_master_status.raw_cplex_status == 101
    assert result.execution.termination_status == "TimeLimit"
    assert result.diagnostics.interrupted_phase == "pricing"


@pytest.mark.parametrize("kind,original_duals", [("main", False), ("extra", True)])
def test_modified_pricing_cannot_certify_convergence(kind, original_duals):
    progress = cg._CGProgress(Queue(), "stub", cg.time.perf_counter(), True)
    progress.put({"phase": "lp", "state": map_cplex_lp_status(1),
                  "raw_status": 1, "objective": 2.5})
    progress.start_phase("pricing", pricing_kind=kind, original_duals=original_duals)
    progress.put({"phase": "pricing", "state": map_cplex_mip_status(101),
                  "raw_status": 101, "objective": 0.0, "best_bound": 0.0})
    assert not progress.result().diagnostics.lp_convergence_proven


def test_second_phase_and_retries_do_not_overwrite_primary_evidence():
    progress = cg._CGProgress(Queue(), "stub", cg.time.perf_counter(), True)
    progress.put({"phase": "lp", "state": map_cplex_lp_status(1),
                  "raw_status": 1, "objective": 2.5})
    progress.start_phase("pricing")
    progress.put({"phase": "pricing", "state": map_cplex_mip_status(101),
                  "raw_status": 101, "objective": 0.0, "best_bound": 0.0})
    progress.put({"phase": "pricing", "pricing_stage": "phase2",
                  "state": map_cplex_mip_status(107), "raw_status": 107})
    progress.end_phase()
    progress.start_phase("pricing", pricing_kind="extra", original_duals=False)
    progress.put({"phase": "pricing", "state": map_cplex_mip_status(105), "raw_status": 105})
    progress.put({"phase": "pricing", "pricing_stage": "phase2",
                  "state": map_cplex_mip_status(102), "raw_status": 102})
    diagnostics = progress.result().diagnostics
    assert diagnostics.pricing_status.raw_cplex_status == 101
    assert diagnostics.pricing_phase2_status.raw_cplex_status == 107
    assert diagnostics.auxiliary_pricing_status.raw_cplex_status == 105
    assert diagnostics.auxiliary_pricing_phase2_status.raw_cplex_status == 102
    assert diagnostics.lp_convergence_proven
    assert diagnostics.pricing_objective == diagnostics.pricing_best_bound == 0.0
    assert progress.result().execution.termination_status == "TimeLimit"


def test_second_phase_optimum_cannot_supply_primary_proof():
    progress = cg._CGProgress(Queue(), "stub", cg.time.perf_counter(), True)
    progress.put({"phase": "lp", "state": map_cplex_lp_status(1),
                  "raw_status": 1, "objective": 2.5})
    progress.start_phase("pricing")
    progress.put({"phase": "pricing", "state": map_cplex_mip_status(107),
                  "raw_status": 107, "objective": 0.0, "best_bound": 1.0})
    progress.put({"phase": "pricing", "pricing_stage": "phase2",
                  "state": map_cplex_mip_status(101), "raw_status": 101,
                  "objective": 0.0, "best_bound": 0.0})
    assert not progress.result().diagnostics.lp_convergence_proven
    progress.start_phase("pricing")
    assert progress.result().diagnostics.pricing_best_bound is None


def test_extra_pricing_time_and_status_are_included(stub_run):
    result = stub_run([(make_slice(1), 0.0, ["z_x_1_0"]), (None, None, [])],
                      finalization_heuristics=True)
    assert result.metrics.pricing_time_s == 6
    assert result.metrics.master_lp_time_s == 3
    assert result.diagnostics.cg_stop_reason == "pricing_converged"
    assert result.diagnostics.lp_convergence_proven
    assert result.diagnostics.auxiliary_pricing_status.raw_cplex_status == 101


def test_duplicate_retry_time_is_included(stub_run):
    result = stub_run([(make_slice(0), 1.0, ["z_x_0_0"]), (None, 0.0, [])],
                      finalization_heuristics=True)
    assert result.metrics.pricing_time_s == 6
    assert result.diagnostics.cg_stop_reason == "duplicate"
    assert not result.diagnostics.lp_convergence_proven


def test_stagnation_has_its_own_stop_reason(stub_run, monkeypatch):
    monkeypatch.setattr(cg, "MAX_STAGNATION", 0)
    result = stub_run([(make_slice(1), 1.0, ["z_x_1_0"])], finalization_heuristics=True)
    assert result.diagnostics.cg_stop_reason == "stagnation"
    assert not result.diagnostics.lp_convergence_proven


@pytest.mark.parametrize("phase,field", [
    ("master_lp", "master_lp_time_s"), ("pricing", "pricing_time_s"),
    ("integer_master", "integer_master_time_s"),
])
def test_interrupted_phase_accounts_only_until_cutoff(monkeypatch, phase, field):
    clock = [0.0]
    monkeypatch.setattr(cg.time, "perf_counter", lambda: clock[0])
    progress = cg._CGProgress(Queue(), "stub", 0.0, True)
    if phase == "integer_master":
        progress.ip_started = 0.0
        progress.stop_cg("duplicate")
    progress.start_phase(phase)
    clock[0] = 1.25
    snapshot = progress.result()
    clock[0] = 9.0  # Parent shutdown happens later than the 4s cutoff.
    result = cg._account_interruption(snapshot, 4.0, "wall_clock_timeout")
    assert getattr(snapshot.metrics, field) == 1.25
    assert getattr(result.metrics, field) == 4.0
    assert result.diagnostics.interrupted_phase == phase
    assert result.diagnostics.cg_stop_reason == ("duplicate" if phase == "integer_master"
                                                else "wall_clock_timeout")
    assert result.metrics.cg_time_s == (0.0 if phase == "integer_master" else 4.0)


def test_preparation_and_export_are_excluded_from_solver_phase_times(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(cg.time, "perf_counter", lambda: clock[0])
    progress = cg._CGProgress(Queue(), "stub", 0.0, True)
    clock[0] = 2.0
    progress.start_phase("master_lp")
    clock[0] = 5.0
    progress.end_phase()
    progress.ip_started = 5.0
    progress.metrics.cg_time_s = 5.0
    progress.start_phase("integer_master")
    clock[0] = 6.0
    progress.end_phase()
    progress.finished = True
    progress.start_phase("layout_export")
    clock[0] = 16.0
    progress.finish()
    result = progress.result()
    assert result.metrics.master_lp_time_s == 3.0
    assert result.metrics.pricing_time_s == 0.0
    assert result.metrics.integer_master_time_s == 1.0
    assert result.metrics.cg_time_s == 5.0
    assert result.execution.total_time_s == 16.0


@pytest.mark.parametrize("bound,expected", [(0.0, 0.0), (float("inf"), None),
                                          (float("nan"), None), (1e20, None)])
def test_pricing_reports_finite_bound_even_without_an_incumbent(bound, expected):
    model = Mock()
    model.solution.get_status.return_value = 108
    model.solution.is_primal_feasible.return_value = False
    model.solution.MIP.get_best_objective.return_value = bound
    queue = Queue()
    assert slave_problem.solve_slave_model(model, queue, None, 4, 1, 1, 1) == (None, None, [])
    message = queue.get_nowait()
    assert message["best_bound"] == expected
    assert message["objective"] is None
    model.solution.get_objective_value.assert_not_called()


@pytest.mark.parametrize("raw", [115, 118, 133, 999])
def test_invalid_pricing_state_cannot_supply_a_bound_certificate(raw):
    progress = cg._CGProgress(Queue(), "stub", cg.time.perf_counter(), True)
    progress.put({"phase": "lp", "state": map_cplex_lp_status(1),
                  "raw_status": 1, "objective": 2.5})
    progress.put({"phase": "pricing", "state": map_cplex_mip_status(raw),
                  "raw_status": raw, "objective": None, "best_bound": 0.0})
    assert not progress.result().diagnostics.lp_convergence_proven


def test_objective_extraction_error_preserves_completed_pricing_status():
    model = Mock()
    model.solution.get_status.return_value = 101
    model.solution.is_primal_feasible.return_value = True
    model.solution.get_objective_value.side_effect = RuntimeError("objective unavailable")
    progress = cg._CGProgress(Queue(), "stub", cg.time.perf_counter(), True)
    with pytest.raises(RuntimeError, match="objective unavailable"):
        slave_problem.solve_slave_model(model, progress, None, 4, 1, 1, 1)
    assert progress.result().diagnostics.pricing_status.raw_cplex_status == 101
    assert progress.result().diagnostics.pricing_objective is None
    assert not progress.result().diagnostics.lp_convergence_proven


def test_iteration_history_separates_build_and_solve(stub_run):
    result = stub_run([(make_slice(1), 1.0, ["z_x_1_0"]), (None, 0.0, [])])
    first, second = result.iterations
    assert [row.iteration for row in result.iterations] == [1, 2]
    assert all(row.completed for row in result.iterations)
    assert (first.pool_before, first.pool_after, first.generated_columns) == (1, 2, 1)
    assert (second.pool_before, second.pool_after, second.generated_columns) == (2, 2, 0)
    assert (first.lp_value, second.lp_value) == (1.5, 2.5)
    assert (first.pricing_objective, second.pricing_objective) == (1.0, 0.0)
    assert (first.stop_reason, second.stop_reason) == ("column_added", "pricing_converged")
    assert first.master_build_time_s == 1
    assert second.master_build_time_s == 0
    assert result.metrics.master_build_time_s == 1
    assert result.metrics.master_solve_time_s == 4
    assert result.metrics.pricing_build_time_s == 2
    assert result.metrics.pricing_solve_time_s == 4
    for field in ("master_lp_time_s", "pricing_time_s", "master_build_time_s",
                  "master_solve_time_s", "pricing_build_time_s", "pricing_solve_time_s"):
        assert sum(getattr(row, field) for row in result.iterations) == getattr(result.metrics, field)


def test_failed_master_does_not_reuse_previous_iteration_values(stub_run, monkeypatch):
    original = cg.solve_master_model
    calls = [0]
    def master(model, queue, manual, relaxed, initial):
        if relaxed:
            calls[0] += 1
            if calls[0] == 2:
                with cg.timed_component(queue, "master_solve"):
                    stub_run.clock[0] += 2
                queue.put({"phase": "lp", "objective": None,
                           "state": map_cplex_lp_status(11, False), "raw_status": 11})
                return None, None, []
        return original(model, queue, manual, relaxed, initial)
    monkeypatch.setattr(cg, "solve_master_model", master)
    result = stub_run([(make_slice(1), 1.0, ["z_x_1_0"])])
    assert result.metrics.lp_value == 1.5
    assert len(result.iterations) == 2
    row = result.iterations[-1]
    assert not row.completed
    assert row.stop_reason == "lp_limit"
    assert row.lp_value is None
    assert row.pricing_objective is None
    assert row.pricing_status.raw_cplex_status is None
    assert row.lp_status.raw_cplex_status == 11


def test_successful_duplicate_retry_closes_one_attempt_before_continue(stub_run):
    result = stub_run([(make_slice(0), 1.0, ["z_x_0_0"]),
                       (make_slice(1), 1.0, ["z_x_1_0"]), (None, 0.0, [])],
                      finalization_heuristics=True)
    assert [row.iteration for row in result.iterations] == [1, 2]
    first = result.iterations[0]
    assert first.stop_reason == "alternative_column_added"
    assert first.pricing_calls == 2
    assert first.pricing_build_time_s == 2
    assert first.pricing_solve_time_s == 4
    assert first.pool_after == 2
    assert first.generated_columns == 1
    assert first.auxiliary_pricing_status.raw_cplex_status == 101


@pytest.mark.parametrize("component", ["master_build", "master_solve", "pricing_build", "pricing_solve"])
def test_partial_iteration_extends_active_component_to_parent_cutoff(monkeypatch, component):
    clock = [0.0]
    monkeypatch.setattr(cg.time, "perf_counter", lambda: clock[0])
    progress = cg._CGProgress(Queue(), "stub", 0.0, True)
    progress.begin_iteration(3)
    phase = "master_lp" if component.startswith("master_") else "pricing"
    progress.start_phase(phase)
    progress.start_component(component)
    clock[0] = 1.25
    snapshot = progress.result(include_history=False)
    clock[0] = 9.0
    result = cg._account_interruption(snapshot, 4.0, "wall_clock_timeout")
    assert getattr(result.metrics, component + "_time_s") == 4.0
    assert len(result.iterations) == 1
    row = result.iterations[0]
    assert getattr(row, component + "_time_s") == 4.0
    assert row.iteration_time_s == 4.0
    assert not row.completed
    assert row.stop_reason == "wall_clock_timeout"
    assert row.pool_before == row.pool_after == 3
    assert snapshot.current_iteration.iteration_time_s == 1.25
    assert snapshot.iterations == []
    assert result.current_iteration is None


def test_history_is_sent_once_per_attempt_and_not_in_snapshots(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(cg.time, "perf_counter", lambda: clock[0])
    queue = Queue()
    progress = cg._CGProgress(queue, "stub", 0.0, True)
    for iteration in range(1, 101):
        progress.begin_iteration(2)
        clock[0] += 0.1
        progress.snapshot()
        progress.end_iteration("column_added", 2)
    messages = []
    while not queue.empty():
        messages.append(queue.get_nowait())
    rows = [message["iteration"] for message in messages if isinstance(message, dict)]
    snapshots = [message for message in messages if not isinstance(message, dict)]
    assert len(rows) == 100
    assert all(snapshot.iterations == [] for snapshot in snapshots)
    assert len(progress.result().iterations) == 100
    assert rows[0].iteration == 1
    assert rows[0].snapshot_time_s == 0.1
    assert rows[-1].iteration == 100


def test_recording_can_be_disabled_without_losing_component_totals(stub_run):
    result = stub_run([(None, 0.0, [])], record_iterations=False)
    assert result.iterations == []
    assert result.metrics.master_build_time_s == 1
    assert result.metrics.master_solve_time_s == 2
    assert result.metrics.pricing_build_time_s == 1
    assert result.metrics.pricing_solve_time_s == 2


def test_pricing_second_phase_has_separate_preparation_and_solve_time(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(cg.time, "perf_counter", lambda: clock[0])
    progress = cg._CGProgress(Queue(), "stub", 0.0, True)
    progress.begin_iteration(1)
    progress.start_phase("pricing")
    model = Mock()
    def solve():
        clock[0] += 2
    def prepare(**kwargs):
        clock[0] += 1
    model.solve.side_effect = solve
    model.linear_constraints.add.side_effect = prepare
    model.solution.get_status.return_value = 101
    model.solution.is_primal_feasible.return_value = True
    model.solution.get_objective_value.return_value = 1
    model.solution.get_values.return_value = [1]
    model.variables.get_names.return_value = ["z_x_0_0"]
    model.objective.get_linear.return_value = [1]
    slave_problem.solve_slave_model(model, progress, None, 4, 1, 1, 1,
                                    finalization_heuristics=True)
    progress.end_phase()
    progress.end_iteration("column_added", 1)
    result = progress.result()
    assert result.metrics.pricing_build_time_s == 1
    assert result.metrics.pricing_solve_time_s == 4
    row = result.iterations[0]
    assert row.pricing_calls == row.pricing_phase2_calls == 1
    assert row.pricing_phase2_status.raw_cplex_status == 101


def test_component_time_excludes_checkpoint_publication(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(cg.time, "perf_counter", lambda: clock[0])
    class SlowQueue:
        def put(self, message):
            clock[0] += 0.25
    progress = cg._CGProgress(SlowQueue(), "stub", 0.0, True)
    progress.begin_iteration(1)
    progress.start_phase("master_lp")
    with cg.timed_component(progress, "master_solve"):
        clock[0] += 1.0
    progress.end_phase()
    assert progress.result().metrics.master_solve_time_s == 1.0
    assert progress.result().metrics.master_lp_time_s > 1.0


def test_second_phase_failure_is_visible_in_its_iteration(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(cg.time, "perf_counter", lambda: clock[0])
    progress = cg._CGProgress(Queue(), "stub", 0.0, True)
    progress.begin_iteration(1)
    progress.start_phase("pricing")
    model = Mock()
    model.solve.side_effect = [None, RuntimeError("phase2 failed")]
    model.solution.get_status.return_value = 101
    model.solution.is_primal_feasible.return_value = True
    model.solution.get_objective_value.return_value = 1
    model.solution.get_values.return_value = [1]
    model.variables.get_names.return_value = ["z_x_0_0"]
    model.objective.get_linear.return_value = [1]
    _, objective, _ = slave_problem.solve_slave_model(
        model, progress, None, 4, 1, 1, 1, finalization_heuristics=True)
    assert objective == 1  # The first-phase incumbent remains usable.
    progress.current_iteration.completed = True
    progress.end_phase()
    progress.end_iteration("column_added", 1)
    row = progress.result().iterations[0]
    assert not row.completed
    assert row.stop_reason == "error"
    assert row.pricing_calls == row.pricing_phase2_calls == 1
    assert row.pricing_status.raw_cplex_status == 101
    assert row.pricing_phase2_status.termination_status == "Error"
    assert row.pricing_phase2_status.raw_cplex_status is None


def test_parent_merges_closed_rows_and_extends_only_active_row(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(cg.time, "perf_counter", lambda: clock[0])
    progress = cg._CGProgress(Queue(), "stub", 0.0, True)
    progress.begin_iteration(1)
    progress.start_phase("master_lp")
    with cg.timed_component(progress, "master_solve"):
        clock[0] = 1.0
    progress.end_phase()
    progress.current_iteration.completed = True
    progress.end_iteration("column_added", 2)
    closed = progress.iterations[0]
    progress.begin_iteration(2)
    progress.start_phase("pricing")
    progress.start_component("pricing_solve")
    clock[0] = 1.25
    snapshot = progress.result(include_history=False)
    messages = [{"iteration": closed}, snapshot]
    class StubQueue:
        def get(self, timeout):
            if messages:
                return messages.pop(0)
            clock[0] += timeout
            raise Empty
        def get_nowait(self):
            raise Empty
        def close(self):
            pass
    process = Mock()
    process.is_alive.return_value = True
    def shutdown(*args):
        clock[0] += 1.0
    process.join.side_effect = shutdown
    monkeypatch.setattr(cg.multiprocessing, "Queue", StubQueue)
    monkeypatch.setattr(cg.multiprocessing, "Process", lambda **kwargs: process)
    result = cg.execute_with_time_limit(0.25, {"case_name": "stub", "bin_width": 4,
        "bin_height": 4, "item_width": 1, "item_height": 1})
    assert [row.iteration for row in result.iterations] == [1, 2]
    assert result.iterations[0].completed
    assert result.iterations[0].iteration_time_s == 1.0
    assert not result.iterations[1].completed
    assert result.iterations[1].stop_reason == "wall_clock_timeout"
    assert result.iterations[1].pricing_solve_time_s == pytest.approx(0.5)
    assert result.iterations[1].iteration_time_s == pytest.approx(0.5)
    assert result.metrics.pricing_solve_time_s == pytest.approx(0.5)
    assert result.execution.total_time_s >= 2.25


def test_second_phase_postprocessing_error_preserves_actual_solver_state():
    progress = cg._CGProgress(Queue(), "stub", cg.time.perf_counter(), True)
    progress.begin_iteration(1)
    progress.start_phase("pricing")
    model = Mock()
    model.solution.get_status.return_value = 101
    model.solution.is_primal_feasible.return_value = True
    model.solution.get_objective_value.return_value = 1
    model.variables.get_names.return_value = ["z_x_0_0"]
    model.objective.get_linear.return_value = [1]
    mapper = Mock()
    first_slice = make_slice(0)
    mapper.map_solution.side_effect = [
        (first_slice, first_slice.get_items(), ["z_x_0_0"], ([], [])),
        RuntimeError("mapping phase2 failed"),
    ]
    solver = slave_problem.SlaveSolver(solution_mapper=mapper)
    _, objective, _ = solver.solve(model, progress, None, 4, 1, 1, 1,
                                   finalization_heuristics=True)
    assert objective == 1
    progress.current_iteration.completed = True
    progress.end_phase()
    progress.end_iteration("column_added", 1)
    row = progress.result().iterations[0]
    assert not row.completed
    assert row.stop_reason == "error"
    assert row.pricing_phase2_status.raw_cplex_status == 101
    assert row.pricing_phase2_status.model_status == 1
    assert row.pricing_phase2_calls == 1


def test_dual_extraction_error_keeps_this_iteration_lp_without_stale_pricing(stub_run, monkeypatch):
    original = cg.solve_master_model
    def master(model, queue, manual, relaxed, initial):
        result = original(model, queue, manual, relaxed, initial)
        if relaxed:
            raise RuntimeError("dual extraction failed")
        return result
    monkeypatch.setattr(cg, "solve_master_model", master)
    result = stub_run([])
    assert result.execution.termination_status == "Error"
    row = result.iterations[0]
    assert row.lp_value == 1.5
    assert row.lp_status.raw_cplex_status == 1
    assert row.master_solve_time_s == 2
    assert not row.completed
    assert row.stop_reason == "error"
    assert row.pricing_status.raw_cplex_status is None
    assert row.pricing_objective is None
