from types import SimpleNamespace

import pytest

from models.column_generation.solution_pool import (
    InvalidPoolSolution, PricingGeometry, PricingPoolOptions, PoolRead,
    candidate_from_values, read_solution_pool,
)


GEOMETRY = PricingGeometry(4, 3, 2, 1, 1)


def model_with_pool(names, rows, coefficients=None, objectives=None):
    coefficients = coefficients or [1.0 if name.startswith("z_") else 0.0 for name in names]
    objectives = objectives or [sum(c * v for c, v in zip(coefficients, row)) for row in rows]
    return SimpleNamespace(
        variables=SimpleNamespace(get_names=lambda: names),
        objective=SimpleNamespace(get_linear=lambda: coefficients),
        solution=SimpleNamespace(pool=SimpleNamespace(
            get_num=lambda: len(rows), get_values=lambda index: rows[index],
            get_objective_value=lambda index: objectives[index])))


def test_auxiliary_windows_and_existing_columns_do_not_count_as_extras():
    names = ["z_x_0_0", "z_x_2_0", "z_x_0_1", "s_0", "s_1"]
    rows = [[1, 0, 0, 1, 0], [1, 0, 0, 0, 1], [0, 1, 0, 1, 0],
            [0, 1, 0, 0, 1], [0, 0, 1, 0, 1], [0, 0, 0, 0, 1]]
    model = model_with_pool(names, rows)
    incumbent = candidate_from_values(names, rows[0], {"pi": {}}, GEOMETRY)
    existing = candidate_from_values(names, rows[4], {"pi": {}}, GEOMETRY)
    result = read_solution_pool(model, {"pi": {}}, GEOMETRY,
                                {existing.master_key}, incumbent)
    assert result.raw_count == result.examined == 6
    assert result.duplicate_incumbent == 2
    assert result.duplicate_pool == 1
    assert result.duplicate_master == 1
    assert result.empty == 1
    assert result.useful_extra == len(result.candidates) == 1
    assert result.candidates[0].placements == ((2, 0, "x"),)


def test_square_orientation_and_different_tilings_have_same_master_identity():
    square = PricingGeometry(3, 3, 1, 1, 2)
    left = candidate_from_values(["z_x_0_0"], [1], {"pi": {}}, square)
    right = candidate_from_values(["z_y_0_0"], [1], {"pi": {}}, square)
    assert left == right
    rectangle = PricingGeometry(2, 2, 2, 1, 2)
    horizontal = candidate_from_values(["z_x_0_0", "z_x_0_1"], [1, 1],
                                       {"pi": {}}, rectangle)
    vertical = candidate_from_values(["z_y_0_0", "z_y_1_0"], [1, 1],
                                     {"pi": {}}, rectangle)
    assert horizontal.placements != vertical.placements
    assert horizontal.master_key == vertical.master_key


def test_current_duals_filter_nonpositive_and_stale_objectives_fail():
    names = ["z_x_0_0", "z_x_2_0"]
    duals = {"pi": {"(0,0)": 1.5, "(2,0)": 0.1}}
    model = model_with_pool(names, [[1, 0], [0, 1]], [-0.5, 0.9])
    result = read_solution_pool(model, duals, GEOMETRY, set(), None)
    assert result.nonpositive == 1
    assert result.candidates[0].value == pytest.approx(0.9)
    with pytest.raises(InvalidPoolSolution, match="objective"):
        read_solution_pool(model, {"pi": {}}, GEOMETRY, set(), None)


def test_limit_applies_after_filtering_and_ranks_by_current_value():
    names = ["z_x_0_0", "z_x_2_0", "z_x_0_1"]
    duals = {"pi": {"(0,0)": 0.9, "(2,0)": 0.2}}
    model = model_with_pool(names, [[1, 0, 0], [0, 1, 0], [0, 0, 1]], [0.1, 0.8, 1])
    result = read_solution_pool(model, duals, GEOMETRY, set(), None, max_extra=1)
    assert result.useful_extra == 3
    assert result.limited == 2
    assert result.candidates[0].value == 1


@pytest.mark.parametrize("names,values", [
    (["z_x_3_0"], [1]),  # outside bin
    (["z_x_0_0", "z_x_1_0"], [1, 1]),  # overlap
    (["z_x_0_0", "z_x_0_1"], [1, 1]),  # different slice windows
    (["z_x_0_0"], [0.3]),
    (["z_x_0_0"], [float("nan")]),
])
def test_invalid_pool_geometry_is_a_correctness_failure(names, values):
    with pytest.raises(InvalidPoolSolution):
        candidate_from_values(names, values, {"pi": {}}, GEOMETRY)


def test_pool_access_error_is_data_and_does_not_invalidate_main_solution():
    model = model_with_pool(["z_x_0_0"], [[1]])

    def unavailable():
        raise RuntimeError("No solution pool")

    model.solution.pool.get_num = unavailable
    result = read_solution_pool(model, {"pi": {}}, GEOMETRY, set(), None)
    assert not result.candidates
    assert result.errors == ["No solution pool"]


def test_real_cplex_pool_on_reused_pricing_uses_current_duals():
    from models.column_generation.slave_problem import IncrementalPricingModel
    from models.common.position_generator import generate_positions_xym

    xy_x, xy_y = generate_positions_xym(4, 3, 2, 1)
    session = IncrementalPricingModel(2, xy_x, xy_y, 4, 1, 2, 3, 1)
    try:
        for duals in ({"pi": {}}, {"pi": {"(0,0)": 0.5}}, {"pi": {}}):
            model = session.prepare(duals)
            for setter in (model.set_log_stream, model.set_results_stream,
                           model.set_warning_stream, model.set_error_stream):
                setter(None)
            model.parameters.threads.set(1)
            model.parameters.mip.pool.intensity.set(2)
            model.parameters.mip.pool.capacity.set(20)
            model.parameters.mip.limits.populate.set(10)
            model.solve()
            incumbent = candidate_from_values(
                model.variables.get_names(), model.solution.get_values(), duals, GEOMETRY,
                coefficients=model.objective.get_linear(),
                reported_objective=model.solution.get_objective_value())
            model.parameters.timelimit.set(0.2)
            model.populate_solution_pool()
            result = read_solution_pool(model, duals, GEOMETRY, set(), incumbent)
            assert not result.errors
            assert result.examined > 0
            assert all(candidate.value > 0 for candidate in result.candidates)
            assert model.parameters.advance.get() == 0
        assert session.build_count == 1
    finally:
        session.close()


@pytest.mark.parametrize("options", [
    {"max_columns": 0}, {"capacity": True}, {"intensity": 5},
    {"mode": "unknown"}, {"populate_time_s": float("nan")}, {"populate_ratio": 0},
])
def test_invalid_options_fail_before_solver_use(options):
    with pytest.raises(ValueError):
        PricingPoolOptions(**options)


@pytest.fixture
def run_cg(monkeypatch):
    import time
    from queue import Queue
    from models.column_generation import column_generation_solver as cg
    from models.column_generation import slave_problem
    from models.column_generation.master_problem import MasterModelBuilder
    from objects.ConfigData import ConfigData

    original_master = cg.create_master_model
    original_slave = slave_problem.create_slave_model
    layouts = []

    def quiet(model):
        for setter in (model.set_log_stream, model.set_results_stream,
                       model.set_warning_stream, model.set_error_stream):
            setter(None)
        model.parameters.threads.set(1)
        model.parameters.randomseed.set(1)
        return model

    monkeypatch.setattr(cg, "create_master_model", lambda *a: quiet(original_master(*a)))
    monkeypatch.setattr(slave_problem, "create_slave_model", lambda *a: quiet(original_slave(*a)))
    monkeypatch.setattr(cg, "export_final_layout", lambda *a: layouts.append(a[-1]))

    def run(options=None, dimensions=(6, 4, 3, 2), **kwargs):
        layouts.clear()
        # Existing comparisons keep an explicit one-column control.
        kwargs.setdefault("use_pricing_pool", options is not None)
        # Exercise pool operations even when greedy could find all improvements.
        kwargs.setdefault("use_greedy_pricing", False)
        result = cg.orchestrator(
            Queue(), None, 3, time.perf_counter(), ConfigData(*dimensions),
            return_structured=True, finalization_heuristics=kwargs.pop("finalization_heuristics", False),
            pool_options=options, **kwargs)
        occupied = set()
        for slice_ in layouts[-1] if layouts else []:
            cells = MasterModelBuilder._slice_cells(slice_)
            assert not occupied & cells
            assert all(0 <= x < dimensions[0] and 0 <= y < dimensions[1] for x, y in cells)
            occupied.update(cells)
        return result

    return run


@pytest.mark.parametrize("mode", ["passive", "populate"])
@pytest.mark.parametrize("dimensions,optimum", [((6, 4, 3, 2), 4), ((4, 6, 2, 3), 4),
                                                 ((6, 6, 2, 2), 9)])
def test_batch_cg_geometry_certificates_and_metrics(run_cg, mode, dimensions, optimum):
    options = PricingPoolOptions(mode=mode, populate_time_s=0.05, populate_ratio=0.2)
    result = run_cg(options, dimensions)
    assert not result.execution.error_message
    assert result.metrics.lp_value == pytest.approx(optimum)
    assert result.metrics.restricted_integer_master == optimum
    if not result.diagnostics.lp_convergence_proven:
        # Bounded master variables can leave a positive duplicate at closure;
        # retrieving alternatives must never turn that into a false certificate.
        assert result.diagnostics.cg_stop_reason == "duplicate"
        assert result.diagnostics.pricing_objective > 0
    assert result.metrics.lp_pool_size == result.metrics.integer_pool_size == result.metrics.pool_size
    assert result.metrics.generated_columns == sum(row.generated_columns for row in result.iterations)
    assert result.metrics.pool_extra_columns == sum(row.pool_extra_columns for row in result.iterations)
    assert all(row.generated_columns <= options.max_columns for row in result.iterations)
    assert result.metrics.pool_examined > 0
    assert result.metrics.pool_read_errors == 0
    # Populate statuses are separate: the main solve's certificate survives.
    assert all(row.pricing_status.raw_cplex_status in (101, 102)
               for row in result.iterations if row.completed)
    if mode == "passive":
        assert result.metrics.pool_calls == 0
        assert result.metrics.pool_search_time_s == 0


def test_one_column_option_preserves_default_path(run_cg, monkeypatch):
    from models.column_generation import column_generation_solver as cg

    def forbidden(*args, **kwargs):
        pytest.fail("One-column mode must not inspect or configure the pool")

    monkeypatch.setattr(cg, "collect_pricing_extras", forbidden)
    monkeypatch.setattr(PricingPoolOptions, "configure", forbidden)
    baseline = run_cg()
    one = run_cg(PricingPoolOptions(max_columns=1))
    assert baseline.metrics.cg_iterations == one.metrics.cg_iterations
    assert baseline.metrics.generated_columns == one.metrics.generated_columns
    assert baseline.metrics.restricted_integer_master == one.metrics.restricted_integer_master
    assert baseline.diagnostics.cg_stop_reason == one.diagnostics.cg_stop_reason


def test_read_errors_preserve_primary_columns_and_closure(run_cg, monkeypatch):
    from models.column_generation import solution_pool

    monkeypatch.setattr(solution_pool, "read_solution_pool", lambda *a, **k:
                        PoolRead(errors=["unavailable pool"]))
    result = run_cg(PricingPoolOptions())
    assert result.metrics.restricted_integer_master == 4
    assert result.diagnostics.lp_convergence_proven
    assert result.metrics.pool_read_errors > 0
    assert result.metrics.pool_extra_columns == 0
    assert result.diagnostics.pool_last_error == "unavailable pool"


def test_pool_options_survive_spawn_and_wall_timeout():
    from models.column_generation.column_generation_solver import execute_with_time_limit

    result = execute_with_time_limit(
        20, instance=dict(case_name="pool_spawn", bin_width=6, bin_height=4,
                         item_width=3, item_height=2),
        finalization_heuristics=False, pool_options=PricingPoolOptions(),
        random_seed=1, threads=1, use_greedy_pricing=False)
    assert not result.execution.error_message
    assert result.metrics.restricted_integer_master == 4
    assert result.metrics.pool_examined > 0


def test_populate_error_keeps_primary_solution_and_evidence(run_cg, monkeypatch):
    import cplex

    def fail(model):
        raise RuntimeError("populate unavailable")

    monkeypatch.setattr(cplex.Cplex, "populate_solution_pool", fail)
    result = run_cg(PricingPoolOptions(mode="populate"))
    assert result.metrics.restricted_integer_master == 4
    assert result.diagnostics.lp_convergence_proven
    assert result.metrics.pool_calls > 0
    assert result.metrics.pool_read_errors > 0
    assert "populate unavailable" in result.diagnostics.pool_last_error


@pytest.mark.parametrize("heuristics", [None, True])
def test_pool_rejects_finalization_heuristics(monkeypatch, heuristics):
    import time
    from queue import Queue
    from models.column_generation.column_generation_solver import orchestrator
    from objects.ConfigData import ConfigData
    from models.column_generation import column_generation_solver as cg

    monkeypatch.setattr(cg, "USE_PRACTICAL_CG_ENHANCEMENTS", True)
    result = orchestrator(Queue(), None, 1, time.perf_counter(), ConfigData(6, 4, 3, 2),
                          return_structured=True, pool_options=PricingPoolOptions(),
                          finalization_heuristics=heuristics)
    assert "only the base algorithm" in result.execution.error_message


@pytest.mark.parametrize("flag,override,options,enabled", [
    (True, None, None, True),
    (False, None, None, False),
    (True, False, None, False),
    (False, True, None, True),
    (False, None, PricingPoolOptions(), True),
    (True, False, PricingPoolOptions(), False),
])
def test_config_and_explicit_pool_selection(run_cg, monkeypatch, flag, override, options, enabled):
    import config
    from models.column_generation import column_generation_solver as cg

    monkeypatch.setattr(config, "USE_PRICING_SOLUTION_POOL", flag)
    monkeypatch.setattr(cg, "USE_PRACTICAL_CG_ENHANCEMENTS", False)

    def forbidden(*args, **kwargs):
        pytest.fail("Disabled pool must not be configured or read; B must not use populate/stabilization")

    import cplex
    monkeypatch.setattr(cplex.Cplex, "populate_solution_pool", forbidden)
    monkeypatch.setattr(cg, "stabilize_duals", forbidden)
    if not enabled:
        monkeypatch.setattr(PricingPoolOptions, "configure", forbidden)
        monkeypatch.setattr(cg, "collect_pricing_extras", forbidden)
    else:
        configure = PricingPoolOptions.configure

        def check_options(options, model):
            assert options.max_columns == 5
            assert options.mode == "passive"
            assert options.capacity == 20
            configure(options, model)
            assert model.parameters.mip.pool.intensity.get() == 1

        monkeypatch.setattr(PricingPoolOptions, "configure", check_options)

    result = run_cg(options, use_pricing_pool=override,
                    finalization_heuristics=None if enabled else False)
    assert not result.execution.error_message
    assert result.metrics.restricted_integer_master == 4
    assert (result.metrics.pool_examined > 0) is enabled
    assert result.metrics.pool_calls == 0
    assert all(row.generated_columns <= (5 if enabled else 1) for row in result.iterations)


@pytest.mark.parametrize("enabled", [False, True])
def test_config_pool_selection_survives_spawn(monkeypatch, enabled):
    import config
    from models.column_generation.column_generation_solver import execute_with_time_limit

    monkeypatch.setattr(config, "USE_PRICING_SOLUTION_POOL", enabled)
    result = execute_with_time_limit(
        20, instance=dict(case_name="pool_config_spawn", bin_width=6, bin_height=4,
                         item_width=3, item_height=2),
        random_seed=1, threads=1, use_greedy_pricing=False)
    assert not result.execution.error_message
    assert result.metrics.restricted_integer_master == 4
    assert (result.metrics.pool_examined > 0) is enabled
    assert result.metrics.pool_calls == 0


def test_partial_batch_update_rebuilds_complete_master(run_cg, monkeypatch):
    from models.column_generation import column_generation_solver as cg

    original = cg.IncrementalMasterModel.add_slice
    calls = []

    def fail_second_update(model, slice_):
        calls.append(slice_.get_id())
        if len(calls) == 2:
            raise RuntimeError("Second column failed after a partial batch update")
        return original(model, slice_)

    monkeypatch.setattr(cg.IncrementalMasterModel, "add_slice", fail_second_update)
    result = run_cg(PricingPoolOptions())
    assert len(calls) >= 2
    assert not result.execution.error_message
    assert result.metrics.restricted_integer_master == 4
    assert result.diagnostics.lp_convergence_proven
    assert result.metrics.lp_pool_size == result.metrics.integer_pool_size == result.metrics.pool_size


def test_pool_component_is_accounted_when_external_monitor_interrupts():
    from models.column_generation.column_generation_solver import _account_interruption
    from utils.execution_result import (
        ColumnGenerationExecutionResult, ColumnGenerationMetrics,
        ColumnGenerationDiagnostics, ColumnGenerationIteration, ExecutionResult,
    )

    result = ColumnGenerationExecutionResult(
        ExecutionResult("case", "cg", None, "Normal", None, 10),
        ColumnGenerationMetrics(pool_calls=1),
        ColumnGenerationDiagnostics(active_phase="pricing", active_component="pool_search",
                                    snapshot_time_s=10),
        current_iteration=ColumnGenerationIteration(iteration=1, pool_calls=1))
    stopped = _account_interruption(result, 12, "wall_clock_timeout")
    assert stopped.metrics.pool_search_time_s == 2
    assert stopped.metrics.pricing_time_s == 2
    assert stopped.metrics.pool_calls == 1
    assert not stopped.diagnostics.lp_convergence_proven
