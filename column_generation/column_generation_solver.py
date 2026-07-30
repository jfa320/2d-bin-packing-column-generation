import multiprocessing
import os
import math
import time
from Objects import Slice
from Objects import Item

from position_generator import generate_positions_xym2
from column_generation.master_problem import * 
from column_generation.pricing_problem import * 
from Config import *
from Utils.bin_visualization import export_bin_solution_to_png

from Objects.ConfigData import ConfigData

MODEL_NAME = "Model5Orchestrator"

EPS = 1e-9  # Numeric tolerance

EPS_MASTER = 1e-4
MAX_STAGNATION = 1000
MAX_EXTRA = 5

# Experimental dual stabilization. To restore the previous behavior,
# keep USE_DUAL_STABILIZATION = False.
USE_DUAL_STABILIZATION = False
ALPHA_DUAL_STABILIZATION = 0.2


def calculate_slice_height(bin_width, bin_height, item_width, item_height, percentage=0.05):
    max_bound = math.floor((bin_height * bin_width) / (item_height * item_width))
    target_items = math.ceil(max_bound * percentage)

    normal_items_per_row = math.floor(bin_width / item_width)
    normal_rows = math.ceil(target_items / normal_items_per_row)
    normal_height = normal_rows * item_height

    rotated_items_per_row = math.floor(bin_width / item_height)
    rotated_rows = math.ceil(target_items / rotated_items_per_row)
    rotated_height = rotated_rows * item_width

    return min(normal_height, rotated_height)

def calculate_physical_item_bound(bin_width, bin_height, item_width, item_height):
    return math.floor((bin_width * bin_height) / (item_width * item_height))


def generate_initial_slices(bin_width, bin_height,
                                item_width, item_height,
                                positions_xy_x, positions_xy_y,
                                max_items):

    slice_height = calculate_slice_height(bin_width, bin_height, item_width, item_height)

    def generate_by_orientation(positions, w, h, rotated):
        slices = []
        placed_items = 0

        positions_set = set(positions)

        # Group positions by row (y)
        positions_by_row = {}
        for (x, y) in positions:
            positions_by_row.setdefault(y, []).append(x)

        for y in sorted(positions_by_row.keys()):
            if placed_items >= max_items:
                break

            slice_ = Slice(height=slice_height, width=bin_width)
            occupied = set()
            x = 0

            # Scan the full bin width
            while x + w <= bin_width:
                if placed_items >= max_items:
                    break

                # Region occupied by the item
                region = {(x + dx, y + dy)
                          for dx in range(w)
                          for dy in range(h)}

                # Avoid overlap inside the slice
                if region & occupied:
                    x += 1
                    continue

                # Validate only the start point
                if (x, y) in positions_set:
                    item = Item(height=h, width=w, rotated=rotated)
                    slice_.place_item(item, x, y)
                    occupied |= region
                    placed_items += 1

                    # Jump exactly by the item width
                    x += w
                else:
                    x += 1

            if slice_.get_item_start_points():
                slices.append(slice_)
                placed_items = 0  # Preserve the original semantics

        return slices

    # Generate non-rotated slices
    non_rotated_slices = generate_by_orientation(
        positions_xy_x, item_width, item_height, rotated=False
    )

    # Generate rotated slices
    rotated_slices = generate_by_orientation(
        positions_xy_y, item_height, item_width, rotated=True
    )

    return non_rotated_slices + rotated_slices


def generate_initial_slices_greedy_uniform(bin_width, bin_height,
                                                item_width, item_height,
                                                max_items):
    slice_height = calculate_slice_height(bin_width, bin_height, item_width, item_height)

    def generate_by_orientation(w, h, rotated):
        slices = []

        for y in range(0, bin_height - h + 1, h):
            slice_ = Slice(height=slice_height, width=bin_width)
            placed_items = 0

            for x in range(0, bin_width - w + 1, w):
                if placed_items >= max_items:
                    break

                item = Item(height=h, width=w, rotated=rotated)
                slice_.place_item(item, x, y)
                placed_items += 1

            if slice_.get_item_start_points():
                slices.append(slice_)

        return slices

    non_rotated_slices = generate_by_orientation(
        item_width, item_height, rotated=False
    )

    rotated_slices = []
    if item_width != item_height:
        rotated_slices = generate_by_orientation(
            item_height, item_width, rotated=True
        )

    return non_rotated_slices + rotated_slices

def build_slice_signature(slice_):
    return tuple(sorted((item.get_position_x(), item.get_position_y(), item.get_rotated()) for item in slice_.get_items()))

def summarize_slice(slice_):
    return sorted((item.get_position_x(), item.get_position_y(), item.get_rotated()) for item in slice_.get_items())

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


def add_no_good_cut(slave_model, active_variables, cut_id):
    if not active_variables:
        return

    add_constraint(
        slave_model,
        [1.0] * len(active_variables),
        active_variables,
        len(active_variables) - 1,
        "L",
        f"nogood_{cut_id}"
    )

def add_non_empty_constraint(slave_model):
    names = []
    values = []

    for name in slave_model.variables.get_names():
        if name.startswith("z_x_") or name.startswith("z_y_"):
            names.append(name)
            values.append(1.0)

    if not names:
        return

    add_constraint(
        slave_model,
        values,
        names,
        1.0,
        "G",
        f"non_empty_{slave_model.linear_constraints.get_num()}"
    )


def get_active_slices(slices, active_master_variables):
    active_ids = set()

    for variable_name in active_master_variables:
        if not variable_name.startswith("p_"):
            continue
        active_ids.add(int(variable_name.split("_")[1]))

    return [slice_ for slice_ in slices if slice_.get_id() in active_ids]


def export_final_layout(case_name, bin_width, bin_height, item_width, item_height, physical_item_bound, active_slices):
    output_path = os.path.join("Results", f"{case_name}_layout.png")
    export_bin_solution_to_png(bin_width, bin_height, item_width, item_height, physical_item_bound, active_slices, output_path)
    print(f"Final layout exported to: {output_path}")


def denormalize_slices_for_output(slices, bin_width_original, bin_height_original, item_width_original, item_height_original, normalized_bin, normalized_item):
    if not normalized_bin and not normalized_item:
        return slices

    slice_height = calculate_slice_height(bin_width_original, bin_height_original, item_width_original, item_height_original)
    denormalized_slices = []

    for slice_ in slices:
        denormalized_items = []

        for item in slice_.get_items():
            x = item.get_position_x()
            y = item.get_position_y()
            width = item.get_width()
            height = item.get_height()

            if normalized_bin:
                original_x = bin_width_original - (y + height)
                original_y = x
                width_original = height
                height_original = width
            else:
                original_x = x
                original_y = y
                width_original = width
                height_original = height

            original_item = Item(
                height=height_original,
                width=width_original,
                rotated=item.get_rotated() ^ normalized_bin ^ normalized_item,
                position_x=original_x,
                position_y=original_y
            )
            denormalized_items.append(original_item)

        denormalized_slices.append(
            Slice(
                height=slice_height,
                width=bin_width_original,
                items=denormalized_items
            )
        )

    return denormalized_slices


# Main orchestrator
def orchestrator(queue, manual_interruption, max_time, initial_time, config_data, case_name="case", return_solution=False):
    try:
        # Reset the Slice ID counter for each run
        Slice.reset_id_counter()
        iterations_without_improvement = 0

        # Read dimensions from config_data
        bin_width_original = config_data.get_bin_width()
        bin_height_original = config_data.get_bin_height()
        item_width_original = config_data.get_item_width()
        item_height_original = config_data.get_item_height()
        bin_width = bin_width_original
        bin_height = bin_height_original
        item_width = item_width_original
        item_height = item_height_original

        normalized_bin = bin_height > bin_width
        normalized_item = item_height > item_width

        if normalized_bin:
            bin_width, bin_height = bin_height, bin_width

        if normalized_item:
            item_width, item_height = item_height, item_width

        slice_height = calculate_slice_height(bin_width, bin_height, item_width, item_height)

        # Generate bin positions
        positions_xy_x, positions_xy_y = generate_positions_xym2(bin_width, bin_height, item_width, item_height)

        physical_item_bound = calculate_physical_item_bound(bin_width, bin_height, item_width, item_height)

        # Generate initial slices using a physical bound, not finite item demand.
        slices = generate_initial_slices(bin_width, bin_height, item_width, item_height, positions_xy_x, positions_xy_y, physical_item_bound)

        iteration = 0

        # Build initial slice signatures to avoid regenerating them later
        generated_signatures = {build_slice_signature(r) for r in slices}
        previous_master_objective = None
        previous_stabilized_dual_prices = None

        while True:
            # TODO: This could be improved by avoiding model recreation on every loop.
            # Instead, one model could be created and new columns (slices) added to it.

            master_model = create_master_model(max_time, slices, bin_height, bin_width, item_height, item_width, positions_xy_x, positions_xy_y)
            # Solve master model
            objective_master, dual_prices, _ = solve_master_model(master_model, queue, manual_interruption, True, initial_time)
            pricing_dual_prices = stabilize_duals(
                dual_prices,
                previous_stabilized_dual_prices
            )
            previous_stabilized_dual_prices = pricing_dual_prices

            if previous_master_objective is None:
                print("Previous relaxed master objective: None (first iteration)")
            else:
                master_improvement = objective_master - previous_master_objective

            slave_model = create_slave_model(max_time, positions_xy_x, positions_xy_y, pricing_dual_prices, bin_width, item_height, item_width, bin_height, slice_height)
            new_slice, objective_value_slave_model, active_variables = solve_slave_model(slave_model, queue, manual_interruption, bin_width, item_height, item_width, slice_height)

            is_duplicate = False

            # Validate duplicates only when a new slice was generated
            if new_slice is not None:
                signature = build_slice_signature(new_slice)
                is_duplicate = signature in generated_signatures

            # Stop if the slave did not return a feasible solution
            if objective_value_slave_model is None:
                print("The slave did not return a feasible solution. Stopping.")
                break

            # If the slave objective is at most EPS, there is no significant improvement yet,
            # but a few additional slices are generated before stopping.
            if objective_value_slave_model <= EPS:
                if not USE_PRACTICAL_CG_ENHANCEMENTS:
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
                        slice_height
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
                    if extra_signature not in generated_signatures:
                        slices.append(new_extra_slice)
                        generated_signatures.add(extra_signature)

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

                if not USE_PRACTICAL_CG_ENHANCEMENTS:
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
                        slice_height
                    )

                    if objective_value_alternativa is None:
                        break

                    if objective_value_alternativa <= EPS:
                        print("[DUPLICATE] No alternative with positive improvement found.")
                        break

                    if new_alternative_slice is None or not alternative_active_variables:
                        break

                    alternative_signature = build_slice_signature(new_alternative_slice)
                    if alternative_signature not in generated_signatures:
                        slices.append(new_alternative_slice)
                        generated_signatures.add(alternative_signature)
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
            generated_signatures.add(signature)
            slices.append(new_slice)

            # Update the counter of iterations without master improvement
            if USE_PRACTICAL_CG_ENHANCEMENTS and previous_master_objective is not None:
                master_improvement = objective_master - previous_master_objective
                if abs(master_improvement) <= EPS_MASTER:
                    iterations_without_improvement += 1
                else:
                    iterations_without_improvement = 0

            # Stop if the master does not improve after MAX_STAGNATION iterations
            if USE_PRACTICAL_CG_ENHANCEMENTS and iterations_without_improvement >= MAX_STAGNATION:
                print("Stopping because of numeric master stagnation.")
                break

            # Update the previous master objective for the next iteration
            previous_master_objective = objective_master
            iteration += 1

        # Solve the final integer master model and get the final objective value
        master_model = create_master_model(max_time, slices, bin_height, bin_width, item_height, item_width, positions_xy_x, positions_xy_y)
        objective_value_slave_model, _, active_master_variables = solve_master_model(master_model, queue, manual_interruption, False, initial_time)
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
        if return_solution:
            return objective_value_slave_model, output_active_slices

        return objective_value_slave_model

    except CplexSolverError as e:
        solver_time = round(time.time() - initial_time, 2)
        handle_solver_error(e, queue, solver_time)
        if return_solution:
            return None, []

        return None

def execute_with_time_limit(max_time, instance=None):
    global model_status, solver_status, objective_value, solver_time
    global exceding_limit_time
    exceding_limit_time = False
    initial_time = time.time()

    # Create a queue to receive subprocess results
    queue = multiprocessing.Queue()

    # Create a shared variable to handle manual interruption
    manual_interruption = multiprocessing.Value('b', True)

    if instance is None:
        instance = get_instance(CASE_NAME)

    config_data = ConfigData(
        bin_width=instance["bin_width"],
        bin_height=instance["bin_height"],
        item_width=instance["item_width"],
        item_height=instance["item_height"]
    )

    # Create the subprocess that runs the function
    process = multiprocessing.Process(target=orchestrator, args=(queue, manual_interruption, max_time, initial_time, config_data, instance["case_name"]))

    # Start the subprocess
    process.start()

    # Monitor the queue while the process is running
    while process.is_alive():
        if manual_interruption.value and time.time() - initial_time > max_time:
            print("Limit time reached. Aborting process.")
            model_status = "14" # PAVER value for a model that returned no answer because of an error
            solver_status = "4" # The solver finished model execution
            solver_time = max_time
            exceding_limit_time = True
            process.terminate()
            process.join()
            break
        time.sleep(0.1)  # Avoid consuming too many resources

    # Print execution results that are later stored in the PAVER trace file
    while not queue.empty():
        message = queue.get()
        if isinstance(message, dict):
            objective_value = message["objectiveValue"]
            model_status = message["modelStatus"]
            solver_status = message["solverStatus"]
            solver_time = message["solverTime"]
            print(f"Optimal value: {objective_value}")
            print(message)
    if exceding_limit_time:
        print("The model exceeded the execution time limit.")
        objective_value = "n/a"
        model_status = "14"

    return instance["case_name"], MODEL_NAME, model_status, solver_status, objective_value, solver_time
