import multiprocessing
import time
from queue import Empty
from dataclasses import replace
from utils.execution_result import ExecutionResult, ColumnGenerationMetrics, ColumnGenerationExecutionResult
from utils.paver_constants import PaverConstants
from objects import Slice

from models.common.position_generator import generate_positions_xym2
from models.column_generation.master_problem import create_master_model, solve_master_model
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
    def __init__(self, queue, case_name, started, structured):
        self.queue = queue
        self.case_name = case_name
        self.started = started
        self.structured = structured
        self.metrics = ColumnGenerationMetrics()
        self.termination = PAVER.TERMINATION_NORMAL
        self.raw_status = None
        self.last_model_status = None
        self.final_model_status = None
        self.error = None
        self.ip_started = None
        self.finished = False

    def result(self):
        now = time.perf_counter()
        metrics = replace(self.metrics)
        if not self.finished and self.ip_started is None:
            metrics = replace(metrics, cg_time_s=now - self.started)
        elif not self.finished:
            metrics = replace(metrics, integer_master_time_s=now - self.ip_started)
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
                            now - self.started, self.raw_status, self.error), metrics)

    def snapshot(self):
        if self.structured:
            self.queue.put(self.result())

    def put(self, message):
        if "error" in message:
            self.error = message["error"]
            self.termination = PAVER.TERMINATION_ERROR
        else:
            state = message["state"]
            self.last_model_status = state.model_status
            termination = str(state.termination_status)
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


def orchestrator(queue, manual_interruption, max_time, initial_time, config_data, case_name="case", return_solution=False, return_structured=False, finalization_heuristics=None):
    progress = _CGProgress(queue, case_name, time.perf_counter(), return_structured)
    queue = progress
    practical_enhancements = USE_PRACTICAL_CG_ENHANCEMENTS if finalization_heuristics is None else finalization_heuristics
    try:
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
        positions_xy_x, positions_xy_y = generate_positions_xym2(bin_width, bin_height, item_width, item_height)

        physical_item_bound = calculate_physical_item_bound(bin_width, bin_height, item_width, item_height)

        # Generate initial slices using a physical bound, not finite item demand.
        slices = generate_initial_slices(bin_width, bin_height, item_width, item_height, positions_xy_x, positions_xy_y, physical_item_bound)

        iteration = 0

        registry = SliceRegistry(slices)
        slices = registry.slices
        previous_master_objective = None
        previous_stabilized_dual_prices = None

        while True:
            # TODO: This could be improved by avoiding model recreation on every loop.
            # Instead, one model could be created and new columns (slices) added to it.

            master_model = create_master_model(max_time, slices, bin_height, bin_width, item_height, item_width, positions_xy_x, positions_xy_y)
            # Solve master model
            objective_master, dual_prices, _ = solve_master_model(master_model, queue, manual_interruption, True, initial_time)
            if objective_master is None or dual_prices is None:
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

            slave_model = create_slave_model(max_time, positions_xy_x, positions_xy_y, pricing_dual_prices, bin_width, item_height, item_width, bin_height, slice_height)
            new_slice, objective_value_slave_model, active_variables = solve_slave_model(slave_model, queue, manual_interruption, bin_width, item_height, item_width, slice_height, finalization_heuristics=finalization_heuristics)

            is_duplicate = False

            # Validate duplicates only when a new slice was generated
            if new_slice is not None:
                signature = build_slice_signature(new_slice)
                is_duplicate = registry.contains(new_slice)

            # Stop if the slave did not return a feasible solution
            if objective_value_slave_model is None:
                print("The slave did not return a feasible solution. Stopping.")
                break

            progress.metrics = replace(progress.metrics, cg_iterations=progress.metrics.cg_iterations + 1)
            progress.snapshot()

            # If the slave objective is at most EPS, there is no significant improvement yet,
            # but a few additional slices are generated before stopping.
            if objective_value_slave_model <= EPS:
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
                    slave_model = create_slave_model(
                        max_time,
                        positions_xy_x,
                        positions_xy_y,
                        pricing_dual_prices,
                        bin_width,
                        item_height,
                        item_width,
                        bin_height,
                        slice_height
                    )

                    # Force the model to generate slices with at least one item
                    add_non_empty_constraint(slave_model)

                    # Force the model not to return the previous slice
                    # Prevent the same slave variables from being active
                    for i, active_variables in enumerate(excluded_solutions):
                        add_no_good_cut(slave_model, active_variables, i)

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
                        progress.metrics = replace(progress.metrics, generated_columns=progress.metrics.generated_columns + 1)
                        progress.snapshot()

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
                    print("Duplicate positive reduced-cost column returned by pricing. Stopping generation.")
                    break

                excluded_solutions = []
                if active_variables:
                    excluded_solutions.append(active_variables)

                added_alternative = False
                for _ in range(MAX_EXTRA):
                    slave_model = create_slave_model(
                        max_time,
                        positions_xy_x,
                        positions_xy_y,
                        pricing_dual_prices,
                        bin_width,
                        item_height,
                        item_width,
                        bin_height,
                        slice_height
                    )

                    add_non_empty_constraint(slave_model)

                    for i, active_variables in enumerate(excluded_solutions):
                        add_no_good_cut(slave_model, active_variables, i)

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

                    if objective_value_alternativa is None:
                        break

                    if objective_value_alternativa <= EPS:
                        print("[DUPLICATE] No alternative with positive improvement found.")
                        break

                    if new_alternative_slice is None or not alternative_active_variables:
                        break

                    alternative_signature = build_slice_signature(new_alternative_slice)
                    if registry.add(new_alternative_slice):
                        progress.metrics = replace(progress.metrics, generated_columns=progress.metrics.generated_columns + 1)
                        progress.snapshot()
                        added_alternative = True
                        break

                    excluded_solutions.append(alternative_active_variables)

                if added_alternative:
                    continue

                print("Duplicate slice detected without a new alternative. Stopping generation.")
                break

            # Stop if the slave did not generate a slice
            if new_slice is None:
                print("The slave did not generate a slice. Stopping.")
                break

            # Add the new slice and its signature
            registry.add(new_slice)
            progress.metrics = replace(progress.metrics, generated_columns=progress.metrics.generated_columns + 1)
            progress.snapshot()

            # Update the counter of iterations without master improvement
            if practical_enhancements and previous_master_objective is not None:
                master_improvement = objective_master - previous_master_objective
                if abs(master_improvement) <= EPS_MASTER:
                    iterations_without_improvement += 1
                else:
                    iterations_without_improvement = 0

            # Stop if the master does not improve after MAX_STAGNATION iterations
            if practical_enhancements and iterations_without_improvement >= MAX_STAGNATION:
                print("Stopping because of numeric master stagnation.")
                break

            # Update the previous master objective for the next iteration
            previous_master_objective = objective_master
            iteration += 1

        # Solve the final integer master model and get the final objective value
        progress.ip_started = time.perf_counter()
        progress.metrics = replace(progress.metrics, cg_time_s=progress.ip_started - progress.started)
        progress.snapshot()
        master_model = create_master_model(max_time, slices, bin_height, bin_width, item_height, item_width, positions_xy_x, positions_xy_y)
        objective_value_slave_model, _, active_master_variables = solve_master_model(master_model, queue, manual_interruption, False, initial_time)
        progress.metrics = replace(progress.metrics, integer_master_time_s=time.perf_counter() - progress.ip_started)
        progress.finished = True
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
        # Return result
        if return_structured:
            result = progress.result()
            progress.queue.put({"result": result, "finished": True})
            return result
        if return_solution:
            return objective_value_slave_model, output_active_slices

        return objective_value_slave_model

    except Exception as e:
        progress.put({"error": str(e)})
        if return_structured:
            result = progress.result()
            progress.queue.put({"result": result, "finished": True})
            return result
        if return_solution:
            return None, []

        return None

def execute_with_time_limit(max_time, instance=None, finalization_heuristics=None):
    started = time.perf_counter()
    result = ColumnGenerationExecutionResult(
        ExecutionResult(instance.get("case_name", CASE_NAME) if instance is not None else CASE_NAME,
                        MODEL_NAME, PAVER.MODEL_STATUS_NO_SOLUTION,
                        PAVER.TERMINATION_ERROR, None, 0.0,
                        error_message="CG child exited without a result"),
        ColumnGenerationMetrics())
    queue = None
    process = None
    timed_out = False
    completed = False
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
            kwargs={"return_structured": True, "finalization_heuristics": finalization_heuristics})
        process.start()
        def consume(message):
            nonlocal result, completed
            if isinstance(message, ColumnGenerationExecutionResult):
                result = message
            elif isinstance(message, dict) and message.get("finished"):
                result = message["result"]
                completed = True

        while True:
            remaining = max_time - (time.perf_counter() - started)
            if remaining <= 0:
                timed_out = True
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
        if not timed_out and (process.exitcode or not completed):
            result = replace(result, execution=replace(result.execution,
                termination_status=PAVER.TERMINATION_ERROR,
                error_message=f"CG child exited with code {process.exitcode}; completed={completed}"))
        if timed_out:
            result = replace(result, execution=replace(result.execution,
                termination_status=PAVER.TERMINATION_TIME_LIMIT,
                error_message="Wall-clock time limit reached"))
    except Exception as exc:
        result = replace(result, execution=replace(result.execution,
            termination_status=PAVER.TERMINATION_ERROR, error_message=str(exc)))
    except KeyboardInterrupt:
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
