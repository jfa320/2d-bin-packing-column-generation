import multiprocessing
import math
import time
from queue import Empty
from dataclasses import replace
from utils.execution_result import (
    ExecutionResult, ColumnGenerationMetrics, ColumnGenerationExecutionResult,
    ColumnGenerationDiagnostics, SolverPhaseStatus,
    ColumnGenerationIteration,
)
from utils.cg_instrumentation import timed_component
from utils.paver_constants import PaverConstants
from objects import Slice

from models.common.position_generator import generate_positions_xym
from models.column_generation.master_problem import (
    IncrementalMasterModel,
    create_master_model,
    solve_master_model,
)
from models.column_generation.slave_problem import create_slave_model, solve_slave_model
from models.column_generation.orchestrator_services import (
    calculate_slice_height,
    calculate_physical_item_bound,
    generate_initial_slices,
    generate_initial_slices_greedy_uniform,
    build_slice_signature,
    summarize_slice,
    add_no_good_cut,
    add_non_empty_constraint,
    get_active_slices,
    denormalize_slices_for_output,
    export_final_layout,
    SliceRegistry,
    ProblemNormalizer,
)
from config import CASE_NAME, USE_PRACTICAL_CG_ENHANCEMENTS, get_instance

from objects.ConfigData import ConfigData

MODEL_NAME = "Model5Orchestrator"
PAVER = PaverConstants

EPS = 1e-9  # Numeric tolerance

EPS_MASTER = 1e-4
MAX_STAGNATION = 1000
MAX_EXTRA = 5

# Experimental dual stabilization. To restore the previous behavior,
# keep USE_DUAL_STABILIZATION = False.
USE_DUAL_STABILIZATION = False
ALPHA_DUAL_STABILIZATION = 0.2


def extract_nonzero_duals(dual_prices, tol=1e-9):
    nonzero_duals = {}
    for key, value in dual_prices.get("pi", {}).items():
        if abs(value) > tol:
            nonzero_duals[key] = value
    return nonzero_duals


def stabilize_duals(current_duals, previous_duals, alpha=ALPHA_DUAL_STABILIZATION):
    if not USE_DUAL_STABILIZATION or previous_duals is None:
        return current_duals

    keys = set(current_duals.get("pi", {}).keys()) | set(previous_duals.get("pi", {}).keys())
    stabilized_duals = {"pi": {}}

    for key in keys:
        current = current_duals.get("pi", {}).get(key, 0.0)
        previous = previous_duals.get("pi", {}).get(key, 0.0)
        stabilized_duals["pi"][key] = alpha * current + (1.0 - alpha) * previous

    return stabilized_duals

def calculate_real_reduced_cost(slice_, dual_prices, w, h):
    dual_sum = 0.0
    
    if(slice_ is None):
        return 0.0, 0, 0.0
    for item in slice_.get_items():
        x = item.get_position_x()
        y = item.get_position_y()
        rotated = item.get_rotated()

        width = h if rotated else w
        height = w if rotated else h

        for dx in range(width):
            for dy in range(height):
                key = f"({x+dx},{y+dy})"
                dual_sum += dual_prices["pi"].get(key, 0.0)

    c_r = len(slice_.get_items())
    reduced_cost_real = c_r - dual_sum

    return reduced_cost_real, c_r, dual_sum


# Main orchestrator
class _CGProgress:
    supports_cg_timing = True

    def __init__(self, queue, case_name, started, structured, record_iterations=True):
        self.queue = queue
        self.case_name = case_name
        self.started = started
        self.structured = structured
        self.metrics = ColumnGenerationMetrics()
        self.diagnostics = ColumnGenerationDiagnostics(active_phase="preparation")
        self.phase_started = started
        self.component_started = None
        self.record_iterations = record_iterations and structured
        self.iterations = []
        self.current_iteration = None
        self.iteration_started = None
        self.iteration_index = 0
        self.iteration_open = False
        self.iteration_error = False
        self.pricing_kind = "main"
        self.pricing_original_duals = True
        self.termination = PAVER.TERMINATION_NORMAL
        self.raw_status = None
        self.last_model_status = None
        self.final_model_status = None
        self.error = None
        self.ip_started = None
        self.finished = False

    def result(self, include_history=True):
        now = time.perf_counter()
        metrics = replace(self.metrics)
        current = replace(self.current_iteration) if self.current_iteration is not None else None
        component = self.diagnostics.active_component
        if component is not None and self.component_started is not None:
            field = component + "_time_s"
            elapsed = max(0.0, now - self.component_started)
            metrics = replace(metrics, **{field: getattr(metrics, field) + elapsed})
            if current is not None:
                setattr(current, field, getattr(current, field) + elapsed)
        phase_field = self._phase_time_field()
        if phase_field is not None and self.phase_started is not None:
            elapsed = max(0.0, now - self.phase_started)
            metrics = replace(metrics, **{phase_field: getattr(metrics, phase_field) + elapsed})
            if current is not None and hasattr(current, phase_field):
                setattr(current, phase_field, getattr(current, phase_field) + elapsed)
        if current is not None:
            current.iteration_time_s = max(0.0, now - self.iteration_started)
            current.snapshot_time_s = now
        if not self.finished and self.ip_started is None:
            metrics = replace(metrics, cg_time_s=now - self.started)
        if metrics.restricted_integer_master is not None:
            model_status = PAVER.MODEL_STATUS_FEASIBLE
        elif self.termination == PAVER.TERMINATION_ERROR or self.error:
            model_status = PAVER.MODEL_STATUS_ERROR
        elif self.final_model_status is not None:
            model_status = self.final_model_status
        elif self.last_model_status is not None:
            model_status = self.last_model_status
        else:
            model_status = PAVER.MODEL_STATUS_NO_SOLUTION
        return ColumnGenerationExecutionResult(
            ExecutionResult(self.case_name, MODEL_NAME, model_status,
                            self.termination, metrics.restricted_integer_master,
                            now - self.started, self.raw_status, self.error), metrics,
            replace(self.diagnostics, snapshot_time_s=now),
            list(self.iterations) if include_history else [], current)

    def begin_iteration(self, pool_size):
        if self.iteration_open:
            return
        self.iteration_open = True
        self.iteration_error = False
        self.iteration_index += 1
        self.iteration_started = time.perf_counter()
        if self.record_iterations:
            self.current_iteration = ColumnGenerationIteration(
                iteration=self.iteration_index, pool_before=pool_size, pool_after=pool_size)

    def end_iteration(self, reason, pool_size=None):
        if not self.iteration_open:
            return
        self.iteration_open = False
        if self.current_iteration is not None:
            now = time.perf_counter()
            row = replace(self.current_iteration, stop_reason=reason,
                          iteration_time_s=max(0.0, now - self.iteration_started),
                          snapshot_time_s=now)
            if self.iteration_error:
                row.completed = False
                row.stop_reason = "error"
            if pool_size is not None:
                row.pool_after = pool_size
            self.iterations.append(row)
            # One frozen row per attempt; snapshots never carry the growing history.
            if self.structured:
                self.queue.put({"iteration": row})
        self.current_iteration = None
        self.iteration_started = None
        self.snapshot()

    def record_column(self, pool_size):
        self.metrics = replace(self.metrics, generated_columns=self.metrics.generated_columns + 1)
        if self.current_iteration is not None:
            self.current_iteration.generated_columns += 1
            self.current_iteration.pool_after = pool_size
        self.snapshot()

    def start_component(self, name, *, pricing_stage=None):
        expected_phase = "master_lp" if name.startswith("master_") else "pricing"
        if self.diagnostics.active_phase != expected_phase:
            return False
        if self.component_started is not None:
            raise RuntimeError("CG timing components cannot overlap")
        self.component_started = None
        self.diagnostics = replace(self.diagnostics, active_component=name)
        if name == "pricing_solve" and self.current_iteration is not None:
            field = "pricing_phase2_calls" if pricing_stage == "phase2" else "pricing_calls"
            setattr(self.current_iteration, field, getattr(self.current_iteration, field) + 1)
        self.snapshot()
        # Publishing the checkpoint is bookkeeping, not work of this component.
        self.component_started = time.perf_counter()
        return True

    def end_component(self, name):
        if self.diagnostics.active_component != name:
            raise RuntimeError("CG timing component mismatch")
        elapsed = max(0.0, time.perf_counter() - self.component_started)
        field = name + "_time_s"
        self.metrics = replace(self.metrics, **{field: getattr(self.metrics, field) + elapsed})
        if self.current_iteration is not None:
            setattr(self.current_iteration, field, getattr(self.current_iteration, field) + elapsed)
        self.component_started = None
        self.diagnostics = replace(self.diagnostics, active_component=None)
        self.snapshot()

    def _phase_time_field(self):
        return {
            "master_lp": "master_lp_time_s", "pricing": "pricing_time_s",
            "integer_master": "integer_master_time_s",
        }.get(self.diagnostics.active_phase)

    def _freeze_phase(self):
        field = self._phase_time_field()
        if field is not None and self.phase_started is not None:
            elapsed = max(0.0, time.perf_counter() - self.phase_started)
            self.metrics = replace(self.metrics, **{field: getattr(self.metrics, field) + elapsed})
            if self.current_iteration is not None and hasattr(self.current_iteration, field):
                setattr(self.current_iteration, field, getattr(self.current_iteration, field) + elapsed)
        self.phase_started = None

    def start_phase(self, phase, *, pricing_kind="main", original_duals=True):
        self._freeze_phase()
        self.phase_started = time.perf_counter()
        self.diagnostics = replace(self.diagnostics, active_phase=phase)
        if phase == "pricing":
            self.pricing_kind = pricing_kind
            self.pricing_original_duals = original_duals
            if pricing_kind == "main":
                self.diagnostics = replace(
                    self.diagnostics, lp_convergence_proven=False, convergence_basis=None,
                    pricing_objective=None, pricing_best_bound=None,
                )
        self.snapshot()

    def end_phase(self):
        self._freeze_phase()
        self.diagnostics = replace(self.diagnostics, active_phase="cg_overhead")
        self.snapshot()

    def stop_cg(self, reason):
        self.diagnostics = replace(self.diagnostics, cg_stop_reason=reason)
        self.snapshot()

    def finish(self):
        self._freeze_phase()
        if self.current_iteration is not None and self.iteration_error:
            self.current_iteration.completed = False
        self.end_iteration(self.diagnostics.cg_stop_reason or "error")
        if self.ip_started is None:
            self.metrics = replace(self.metrics, cg_time_s=time.perf_counter() - self.started)
        self.finished = True
        self.diagnostics = replace(self.diagnostics, active_phase=None)

    def phase_stop_reason(self, phase, fallback):
        status = getattr(self.diagnostics, phase + "_status")
        if status.termination_status == PAVER.TERMINATION_ERROR:
            return "error"
        if status.termination_status not in (None, PAVER.TERMINATION_NORMAL):
            return phase + "_limit"
        return fallback

    def _record_pricing_evidence(self, message):
        objective, bound = message.get("objective"), message.get("best_bound")
        self.diagnostics = replace(
            self.diagnostics, pricing_objective=objective, pricing_best_bound=bound,
        )
        state = message["state"]
        lp = self.diagnostics.lp_status
        if (not self.pricing_original_duals
                or lp.model_status != PAVER.MODEL_STATUS_OPTIMAL
                or lp.termination_status != PAVER.TERMINATION_NORMAL
                or self.metrics.lp_value is None or not math.isfinite(self.metrics.lp_value)
                or state.model_status not in {PAVER.MODEL_STATUS_OPTIMAL,
                                               PAVER.MODEL_STATUS_FEASIBLE,
                                               PAVER.MODEL_STATUS_NO_SOLUTION}
                or state.termination_status == PAVER.TERMINATION_ERROR
                or (objective is not None and objective > EPS)):
            return
        basis = None
        if (state.model_status == PAVER.MODEL_STATUS_OPTIMAL
                and state.has_feasible_solution and objective is not None
                and math.isfinite(objective) and objective <= EPS):
            basis = "optimal_pricing"
        elif bound is not None and math.isfinite(bound) and bound <= EPS:
            basis = "pricing_upper_bound"
        if basis is not None:
            self.diagnostics = replace(
                self.diagnostics, lp_convergence_proven=True, convergence_basis=basis,
            )

    def snapshot(self):
        if self.structured:
            self.queue.put(self.result(include_history=False))

    def put(self, message):
        if "error" in message:
            self.iteration_error = True
            self.error = message["error"]
            self.termination = PAVER.TERMINATION_ERROR
            self.diagnostics = replace(
                self.diagnostics, interrupted_phase=self.diagnostics.active_phase,
                cg_stop_reason=self.diagnostics.cg_stop_reason or "error",
            )
            if (message.get("phase") == "pricing" and message.get("pricing_stage") == "phase2"
                    and not message.get("solve_reported", False)):
                field = ("auxiliary_pricing_phase2_status" if self.pricing_kind != "main"
                         else "pricing_phase2_status")
                status = SolverPhaseStatus(PAVER.MODEL_STATUS_ERROR, PAVER.TERMINATION_ERROR, None)
                self.diagnostics = replace(self.diagnostics, **{field: status})
                if self.current_iteration is not None:
                    setattr(self.current_iteration, field, status)
        else:
            state = message["state"]
            self.last_model_status = state.model_status
            termination = str(state.termination_status)
            if termination == PAVER.TERMINATION_ERROR:
                self.iteration_error = True
            phase = message["phase"]
            status_field = {"lp": "lp_status", "ip": "integer_master_status"}.get(phase)
            if phase == "pricing":
                auxiliary = self.pricing_kind != "main"
                second = message.get("pricing_stage") == "phase2"
                status_field = (("auxiliary_pricing" if auxiliary else "pricing")
                                + ("_phase2" if second else "") + "_status")
                if not auxiliary and not second:
                    self._record_pricing_evidence(message)
            if status_field is not None:
                status = SolverPhaseStatus(state.model_status, termination, message["raw_status"])
                self.diagnostics = replace(self.diagnostics, **{
                    status_field: status,
                })
                if self.current_iteration is not None and hasattr(self.current_iteration, status_field):
                    setattr(self.current_iteration, status_field, status)
            if self.current_iteration is not None:
                if phase == "lp" and state.has_feasible_solution:
                    self.current_iteration.lp_value = message.get("objective")
                elif phase == "pricing":
                    if not second and not auxiliary:
                        self.current_iteration.pricing_objective = message.get("objective")
                        self.current_iteration.pricing_best_bound = message.get("best_bound")
            if termination != PAVER.TERMINATION_NORMAL:
                self.diagnostics = replace(
                    self.diagnostics, interrupted_phase={"lp": "master_lp", "ip": "integer_master"}.get(phase, phase),
                )
            # A normal final master must not hide an earlier abnormal solve.
            if (self.termination == PAVER.TERMINATION_NORMAL
                    or termination == PAVER.TERMINATION_ERROR):
                self.termination = termination
                self.raw_status = message["raw_status"]
            if (message["phase"] == "lp"
                    and state.model_status == PAVER.MODEL_STATUS_OPTIMAL
                    and state.has_feasible_solution and message["objective"] is not None):
                self.metrics = replace(self.metrics, lp_value=message["objective"])
            if (message["phase"] == "ip" and state.has_feasible_solution
                    and message["objective"] is not None):
                self.metrics = replace(self.metrics, restricted_integer_master=message["objective"])
            if message["phase"] == "ip":
                self.final_model_status = state.model_status
        self.snapshot()


def orchestrator(queue, manual_interruption, max_time, initial_time, config_data, case_name="case", return_solution=False, return_structured=False, finalization_heuristics=None, record_iterations=True):
    progress = _CGProgress(queue, case_name, time.perf_counter(), return_structured, record_iterations)
    queue = progress
    practical_enhancements = USE_PRACTICAL_CG_ENHANCEMENTS if finalization_heuristics is None else finalization_heuristics
    try:
        progress.snapshot()
        # Reset the Slice ID counter for each run
        Slice.reset_id_counter()
        iterations_without_improvement = 0

        normalized_problem = ProblemNormalizer().normalize(config_data)
        bin_width = normalized_problem.bin_width
        bin_height = normalized_problem.bin_height
        item_width = normalized_problem.item_width
        item_height = normalized_problem.item_height
        bin_width_original = normalized_problem.original_bin_width
        bin_height_original = normalized_problem.original_bin_height
        item_width_original = normalized_problem.original_item_width
        item_height_original = normalized_problem.original_item_height
        normalized_bin = normalized_problem.normalized_bin
        normalized_item = normalized_problem.normalized_item
        slice_height = normalized_problem.slice_height

        # Generate bin positions
        positions_xy_x, positions_xy_y = generate_positions_xym(bin_width, bin_height, item_width, item_height)

        physical_item_bound = calculate_physical_item_bound(bin_width, bin_height, item_width, item_height)

        # Generate initial slices using a physical bound, not finite item demand.
        slices = generate_initial_slices(bin_width, bin_height, item_width, item_height, positions_xy_x, positions_xy_y, physical_item_bound)

        iteration = 0

        registry = SliceRegistry(slices)
        slices = registry.slices
        previous_master_objective = None
        previous_stabilized_dual_prices = None

        def prepare_pricing(duals, excluded=None):
            with timed_component(queue, "pricing_build"):
                model = create_slave_model(
                    max_time, positions_xy_x, positions_xy_y, duals,
                    bin_width, item_height, item_width, bin_height, slice_height)
                if excluded is not None:
                    add_non_empty_constraint(model)
                    for index, active in enumerate(excluded):
                        add_no_good_cut(model, active, index)
                return model

        progress.begin_iteration(len(slices))
        progress.start_phase("master_lp")
        with timed_component(queue, "master_build"):
            master_model = create_master_model(
                max_time, slices, bin_height, bin_width, item_height, item_width,
                positions_xy_x, positions_xy_y,
            )
            incremental_master = IncrementalMasterModel(
                master_model, slices, bin_height, bin_width,
            )
        synchronized_slice_count = len(slices)
        progress.end_phase()

        while True:
            progress.begin_iteration(len(slices))
            progress.start_phase("master_lp")
            with timed_component(queue, "master_build"):
                pending_slices = slices[synchronized_slice_count:]
                if pending_slices:
                    try:
                        for slice_ in pending_slices:
                            incremental_master.add_slice(slice_)
                    except Exception as error:
                        # Rebuild a partially updated model from the complete pool.
                        print("Incremental master update failed; rebuilding the master: "
                              f"{error}")
                        master_model = create_master_model(
                            max_time, slices, bin_height, bin_width, item_height,
                            item_width, positions_xy_x, positions_xy_y,
                        )
                        incremental_master = IncrementalMasterModel(
                            master_model, slices, bin_height, bin_width,
                        )
                    synchronized_slice_count = len(slices)

            # Solve master model
            objective_master, dual_prices, _ = solve_master_model(master_model, queue, manual_interruption, True, initial_time)
            progress.end_phase()
            if objective_master is None or dual_prices is None:
                progress.stop_cg(progress.phase_stop_reason("lp", "lp_failure"))
                break
            pricing_dual_prices = dual_prices if finalization_heuristics is False else stabilize_duals(
                dual_prices,
                previous_stabilized_dual_prices
            )
            previous_stabilized_dual_prices = pricing_dual_prices

            if previous_master_objective is None:
                print("Previous relaxed master objective: None (first iteration)")
            else:
                master_improvement = objective_master - previous_master_objective

            progress.start_phase("pricing", original_duals=pricing_dual_prices is dual_prices)
            slave_model = prepare_pricing(pricing_dual_prices)
            new_slice, objective_value_slave_model, active_variables = solve_slave_model(slave_model, queue, manual_interruption, bin_width, item_height, item_width, slice_height, finalization_heuristics=finalization_heuristics)
            progress.end_phase()

            is_duplicate = False

            # Validate duplicates only when a new slice was generated
            if new_slice is not None:
                signature = build_slice_signature(new_slice)
                is_duplicate = registry.contains(new_slice)

            # Stop if the slave did not return a feasible solution
            if objective_value_slave_model is None:
                progress.stop_cg("pricing_converged" if progress.diagnostics.lp_convergence_proven
                                 else progress.phase_stop_reason("pricing", "pricing_no_solution"))
                print("The slave did not return a feasible solution. Stopping.")
                break

            progress.metrics = replace(progress.metrics, cg_iterations=progress.metrics.cg_iterations + 1)
            if progress.current_iteration is not None:
                progress.current_iteration.completed = True
            progress.snapshot()

            # If the slave objective is at most EPS, there is no significant improvement yet,
            # but a few additional slices are generated before stopping.
            if objective_value_slave_model <= EPS:
                progress.stop_cg("pricing_converged" if progress.diagnostics.lp_convergence_proven
                                 else progress.phase_stop_reason("pricing", "pricing_nonpositive_unproven"))
                if not practical_enhancements:
                    print("No positive reduced-cost column found. Stopping generation.")
                    break

                excluded_solutions = []

                # Exclude the current slave solution to force a new slice in the next iteration
                if active_variables:
                    excluded_solutions.append(active_variables)

                # Start generating extra slices for up to MAX_EXTRA iterations
                # or until a stopping condition is met
                for _ in range(MAX_EXTRA):
                    progress.start_phase("pricing", pricing_kind="extra", original_duals=False)
                    slave_model = prepare_pricing(pricing_dual_prices, excluded_solutions)

                    # Solve the modified slave model
                    new_extra_slice, objective_value_extra, extra_active_variables = solve_slave_model(
                        slave_model,
                        queue,
                        manual_interruption,
                        bin_width,
                        item_height,
                        item_width,
                        slice_height,
                        finalization_heuristics=finalization_heuristics
                    )
                    progress.end_phase()

                    # Stop extra-slice generation if the slave is infeasible
                    if objective_value_extra is None:
                        break

                    # Do not add a slice if the objective value is clearly negative
                    if objective_value_extra < -EPS:
                        print("[EXTRA] Slave objective < -EPS. Slice not added.")
                        break

                    # Stop if no extra slice was generated
                    if new_extra_slice is None:
                        print("[EXTRA] No slice was generated. Stopping.")
                        break

                    # Stop if no slave variable is active
                    if not extra_active_variables:
                        print("[EXTRA] No hay variables active_variables. Corte.")
                        break

                    # Build the new extra slice signature to validate duplicates
                    extra_signature = build_slice_signature(new_extra_slice)

                    # Add the extra slice if its signature has not been generated before
                    if registry.add(new_extra_slice):
                        progress.record_column(len(slices))

                    # Exclude the current slave solution to force a new slice in the next iteration
                    excluded_solutions.append(extra_active_variables)

                break

            # Stop on duplicate slices to avoid cycles
            if is_duplicate:
                reduced_cost_real, item_count, dual_sum = calculate_real_reduced_cost(new_slice, dual_prices, item_width, item_height)
                print(
                    "Duplicate slice detected. "
                    f"Slave objective={objective_value_slave_model}, "
                    f"items={item_count}, "
                    f"occupationDualSum={dual_sum}, "
                    f"fullReducedCost={reduced_cost_real}"
                )

                if not practical_enhancements:
                    progress.stop_cg("duplicate")
                    print("Duplicate positive reduced-cost column returned by pricing. Stopping generation.")
                    break

                excluded_solutions = []
                if active_variables:
                    excluded_solutions.append(active_variables)

                added_alternative = False
                for _ in range(MAX_EXTRA):
                    progress.start_phase("pricing", pricing_kind="duplicate_retry", original_duals=False)
                    slave_model = prepare_pricing(pricing_dual_prices, excluded_solutions)

                    new_alternative_slice, objective_value_alternativa, alternative_active_variables = solve_slave_model(
                        slave_model,
                        queue,
                        manual_interruption,
                        bin_width,
                        item_height,
                        item_width,
                        slice_height,
                        finalization_heuristics=finalization_heuristics
                    )
                    progress.end_phase()

                    if objective_value_alternativa is None:
                        break

                    if objective_value_alternativa <= EPS:
                        print("[DUPLICATE] No alternative with positive improvement found.")
                        break

                    if new_alternative_slice is None or not alternative_active_variables:
                        break

                    alternative_signature = build_slice_signature(new_alternative_slice)
                    if registry.add(new_alternative_slice):
                        progress.record_column(len(slices))
                        added_alternative = True
                        break

                    excluded_solutions.append(alternative_active_variables)

                if added_alternative:
                    progress.end_iteration("alternative_column_added", len(slices))
                    continue

                print("Duplicate slice detected without a new alternative. Stopping generation.")
                progress.stop_cg("duplicate")
                break

            # Stop if the slave did not generate a slice
            if new_slice is None:
                progress.stop_cg("pricing_no_column")
                print("The slave did not generate a slice. Stopping.")
                break

            # Add the new slice and its signature
            registry.add(new_slice)
            progress.record_column(len(slices))

            # Update the counter of iterations without master improvement
            if practical_enhancements and previous_master_objective is not None:
                master_improvement = objective_master - previous_master_objective
                if abs(master_improvement) <= EPS_MASTER:
                    iterations_without_improvement += 1
                else:
                    iterations_without_improvement = 0

            # Stop if the master does not improve after MAX_STAGNATION iterations
            if practical_enhancements and iterations_without_improvement >= MAX_STAGNATION:
                progress.stop_cg("stagnation")
                print("Stopping because of numeric master stagnation.")
                break

            # Update the previous master objective for the next iteration
            previous_master_objective = objective_master
            iteration += 1
            progress.end_iteration("column_added", len(slices))

        progress.end_iteration(progress.diagnostics.cg_stop_reason, len(slices))
        # Solve the final integer master model and get the final objective value
        progress.ip_started = time.perf_counter()
        progress.metrics = replace(progress.metrics, cg_time_s=progress.ip_started - progress.started)
        progress.start_phase("integer_master")
        master_model = create_master_model(max_time, slices, bin_height, bin_width, item_height, item_width, positions_xy_x, positions_xy_y)
        objective_value_slave_model, _, active_master_variables = solve_master_model(master_model, queue, manual_interruption, False, initial_time)
        progress.end_phase()
        progress.finished = True
        progress.start_phase("layout_export")
        # Freeze phase times before layout export.
        # Export the final layout using only active slices in the final master solution
        active_slices = get_active_slices(slices, active_master_variables)
        output_active_slices = denormalize_slices_for_output(
            active_slices,
            bin_width_original,
            bin_height_original,
            item_width_original,
            item_height_original,
            normalized_bin,
            normalized_item
        )
        if output_active_slices:
            export_final_layout(case_name, bin_width_original, bin_height_original, item_width_original, item_height_original, physical_item_bound, output_active_slices)
        else:
            print("No active slice was generated in the final master solution. Layout not exported.")
        progress.finish()
        # Return result
        if return_structured:
            result = progress.result()
            progress.queue.put({"result": replace(result, iterations=[]), "finished": True})
            return result
        if return_solution:
            return objective_value_slave_model, output_active_slices

        return objective_value_slave_model

    except Exception as e:
        progress.put({"error": str(e)})
        progress.finish()
        if return_structured:
            result = progress.result()
            progress.queue.put({"result": replace(result, iterations=[]), "finished": True})
            return result
        if return_solution:
            return None, []

        return None

def _account_interruption(result, stopped_at, reason):
    """Extend the last snapshot to the parent's cutoff, excluding shutdown time."""
    diagnostics = result.diagnostics
    phase = diagnostics.active_phase
    elapsed = (0.0 if diagnostics.snapshot_time_s is None
               else max(0.0, stopped_at - diagnostics.snapshot_time_s))
    changes = {}
    field = {"master_lp": "master_lp_time_s", "pricing": "pricing_time_s",
             "integer_master": "integer_master_time_s"}.get(phase)
    if field is not None:
        changes[field] = getattr(result.metrics, field) + elapsed
    component = diagnostics.active_component
    if component is not None:
        component_field = component + "_time_s"
        changes[component_field] = getattr(result.metrics, component_field) + elapsed
    if phase in {"preparation", "cg_overhead", "master_lp", "pricing"}:
        changes["cg_time_s"] = result.metrics.cg_time_s + elapsed
    iterations = list(result.iterations)
    current = result.current_iteration
    if current is not None and not any(row.iteration == current.iteration for row in iterations):
        current = replace(current, completed=False, stop_reason=reason,
                          iteration_time_s=current.iteration_time_s + elapsed,
                          snapshot_time_s=stopped_at)
        for current_field in (field, component + "_time_s" if component is not None else None):
            if current_field is not None and hasattr(current, current_field):
                setattr(current, current_field, getattr(current, current_field) + elapsed)
        iterations.append(current)
    return replace(result, metrics=replace(result.metrics, **changes), diagnostics=replace(
        diagnostics, cg_stop_reason=diagnostics.cg_stop_reason or reason,
        interrupted_phase=phase or diagnostics.interrupted_phase,
        active_phase=None, active_component=None, snapshot_time_s=stopped_at,
    ), iterations=iterations, current_iteration=None)


def execute_with_time_limit(max_time, instance=None, finalization_heuristics=None, record_iterations=True):
    started = time.perf_counter()
    result = ColumnGenerationExecutionResult(
        ExecutionResult(instance.get("case_name", CASE_NAME) if instance is not None else CASE_NAME,
                        MODEL_NAME, PAVER.MODEL_STATUS_NO_SOLUTION,
                        PAVER.TERMINATION_ERROR, None, 0.0,
                        error_message="CG child exited without a result"),
        ColumnGenerationMetrics(),
        ColumnGenerationDiagnostics(active_phase="setup", snapshot_time_s=started))
    queue = None
    process = None
    timed_out = False
    completed = False
    stopped_at = None
    history = {}

    def attach_history():
        nonlocal result
        for row in result.iterations:
            history[row.iteration] = row
        current = result.current_iteration
        if current is not None and current.iteration in history:
            current = None
        result = replace(result, iterations=[history[key] for key in sorted(history)],
                         current_iteration=current)
    try:
        if instance is None:
            instance = get_instance(CASE_NAME)
        queue = multiprocessing.Queue()
        config_data = ConfigData(
            bin_width=instance["bin_width"], bin_height=instance["bin_height"],
            item_width=instance["item_width"], item_height=instance["item_height"])
        process = multiprocessing.Process(
            target=orchestrator,
            args=(queue, multiprocessing.Value('b', True), max_time, started,
                  config_data, instance["case_name"]),
            kwargs={"return_structured": True, "finalization_heuristics": finalization_heuristics,
                    "record_iterations": record_iterations})
        process.start()
        def consume(message):
            nonlocal result, completed
            if isinstance(message, ColumnGenerationExecutionResult):
                result = message
                for row in message.iterations:
                    history[row.iteration] = row
            elif isinstance(message, dict) and "iteration" in message:
                row = message["iteration"]
                history[row.iteration] = row
            elif isinstance(message, dict) and message.get("finished"):
                result = message["result"]
                for row in result.iterations:
                    history[row.iteration] = row
                completed = True

        while True:
            remaining = max_time - (time.perf_counter() - started)
            if remaining <= 0:
                timed_out = True
                stopped_at = time.perf_counter()
                break
            try:
                message = queue.get(timeout=min(0.05, remaining))
                consume(message)
            except Empty:
                if not process.is_alive():
                    break
        if timed_out and process.is_alive():
            process.terminate()
        process.join(0.5)
        if process.is_alive():
            process.kill()
            process.join(0.5)
        while True:
            try:
                get_nowait = queue.get_nowait
            except AttributeError:
                break
            try:
                consume(get_nowait())
            except Empty:
                break
        attach_history()
        if not timed_out and (process.exitcode or not completed):
            result = _account_interruption(
                result, result.diagnostics.snapshot_time_s or started, "child_exit")
            result = replace(result, execution=replace(result.execution,
                termination_status=PAVER.TERMINATION_ERROR,
                error_message=f"CG child exited with code {process.exitcode}; completed={completed}"))
        if timed_out:
            result = _account_interruption(result, stopped_at, "wall_clock_timeout")
            result = replace(result, execution=replace(result.execution,
                termination_status=PAVER.TERMINATION_TIME_LIMIT,
                error_message="Wall-clock time limit reached"))
    except Exception as exc:
        attach_history()
        result = _account_interruption(result, time.perf_counter(), "error")
        result = replace(result, execution=replace(result.execution,
            termination_status=PAVER.TERMINATION_ERROR, error_message=str(exc)))
    except KeyboardInterrupt:
        attach_history()
        result = _account_interruption(result, time.perf_counter(), "user_interrupt")
        result = replace(result, execution=replace(result.execution,
            termination_status=PAVER.TERMINATION_USER_INTERRUPT,
            error_message="Execution interrupted by user"))
    finally:
        if process is not None and process.is_alive():
            process.terminate()
            process.join(0.5)
            if process.is_alive():
                process.kill()
                process.join(0.5)
        if queue is not None:
            queue.close()
    return replace(result, execution=replace(result.execution,
        total_time_s=time.perf_counter() - started))
