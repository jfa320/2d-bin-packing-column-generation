import cplex
from cplex.exceptions import CplexSolverError
from Utils.model_functions import *
from Config import *
from Objects import Slice
from Objects import Item

MODEL_NAME = "Model5SlaveAlternative"
DISABLE_DUPLICATE_CONSTRAINT_CHECK = True  # Set True to disable duplicate constraint checks

EPS = 1e-9  # Numeric tolerance


def build_items(variable_names, variable_values, height_item, width_item):
    items = []

    for name, value in zip(variable_names, variable_values):
        if not name.startswith("z_") or value <= 0.5:
            continue

        parts = name.split("_")
        # z_<rot>_<x>_<y>
        rot = parts[1]
        x_value = int(parts[2])
        y_value = int(parts[3])

        rotated = (rot == "y")

        height = width_item if rotated else height_item
        width = height_item if rotated else width_item

        item = Item(
            height=height,
            width=width,
            rotated=rotated,
            position_x=x_value,
            position_y=y_value
        )

        if item not in items:
            items.append(item)

    return items


def build_occupied_positions(variable_names, variable_values, height_item, width_item):
    positions_occupied = set()

    for name, value in zip(variable_names, variable_values):
        if not name.startswith("z_") or value <= 0.5:
            continue

        parts = name.split("_")
        rot = parts[1]
        x0 = int(parts[2])
        y0 = int(parts[3])

        rotated = (rot == "y")
        height = width_item if rotated else height_item
        width = height_item if rotated else width_item

        for dx in range(width):
            for dy in range(height):
                positions_occupied.add((x0 + dx, y0 + dy))

    positions_occupied = list(positions_occupied)
    return positions_occupied


def get_max_y(positions_occupied, height_item, width_item, items):
    # TODO: Revisar si este metodo es necesario
    if not positions_occupied:
        return None  # Handle the empty-list case
    item_pos_y_max = max(items, key=lambda item: item.get_position_y())
    return item_pos_y_max.get_position_y() + item_pos_y_max.get_height()


def rects_overlap(x1, y1, w1, h1, x2, y2, w2, h2):
    return not (
        x1 + w1 <= x2 or x2 + w2 <= x1 or
        y1 + h1 <= y2 or y2 + h2 <= y1
    )


def create_slave_model(max_time, xy_x, xy_y, dual_values, width_bin, height_item_sin_rotar, width_item_sin_rotar, height_bin, slice_height):
    print("--------------------------------------------------------------------------------------------------------------------")
    print("IN - Create Slave Model")
    a_i = dual_values
    h = height_item_sin_rotar
    w = width_item_sin_rotar
    width = width_bin
    height = height_bin
    positions = set(xy_x).union(xy_y)
    non_rotated_positions = xy_x
    rotated_positions = xy_y
    positions = list(positions)  # Convertir a lista para iterar
    positions.sort()  # Ordenar los pares (a, b) para consistencia

    valid_x_positions = []
    for (a, b) in non_rotated_positions:
        if a + w <= width and b + h <= height:
            valid_x_positions.append((a, b))

    valid_y_positions = []
    for (a, b) in rotated_positions:
        if a + h <= width and b + w <= height:
            valid_y_positions.append((a, b))

    # R[(a,b,t)] = cells covered by an item starting at (a,b,t)
    occupied_regions = {}

    for (a, b) in valid_x_positions:
        occupied_regions[(a, b, 'x')] = [
            (x, y)
            for x in range(a, a + w)
            for y in range(b, b + h)
        ]

    for (a, b) in valid_y_positions:
        occupied_regions[(a, b, 'y')] = [
            (x, y)
            for x in range(a, a + h)
            for y in range(b, b + w)
        ]

    try:
        # Create the model
        model = cplex.Cplex()
        model.parameters.preprocessing.presolve.set(0)
        # model.set_problem_type(cplex.Cplex.problem_type.LP)
        model.objective.set_sense(model.objective.sense.maximize)

        model.parameters.timelimit.set(max_time)
        initial_time = model.get_time()
        added_constraints = set()

        # Objective function
        rotated_z_vars = []
        non_rotated_z_vars = []
        obj_coeffs = []

        # Helper to sum duals over cells covered by (a,b,t)
        def calculate_dual_sum(a, b, t):
            covered_cells = occupied_regions[(a, b, t)]
            return sum(a_i["pi"].get(f"({x},{y})", 0.0) for (x, y) in covered_cells)

        # Non-rotated variables
        # ---------------------------------------------------------------------
        for (a, b) in valid_x_positions:
            var_name = f"z_x_{a}_{b}"
            non_rotated_z_vars.append(var_name)

            dual_sum = calculate_dual_sum(a, b, 'x')
            coeff = 1.0 - dual_sum
            obj_coeffs.append(coeff)

        add_variables(model, non_rotated_z_vars, obj_coeffs, "B")
        obj_coeffs.clear()

        # ---------------------------------------------------------------------
        # Rotated variables
        # ---------------------------------------------------------------------
        for (a, b) in valid_y_positions:
            var_name = f"z_y_{a}_{b}"
            rotated_z_vars.append(var_name)

            dual_sum = calculate_dual_sum(a, b, 'y')
            coeff = 1.0 - dual_sum
            obj_coeffs.append(coeff)

        add_variables(model, rotated_z_vars, obj_coeffs, "B")
        obj_coeffs.clear()

        valid_y_bases = sorted({b for (_, b) in valid_x_positions + valid_y_positions})
        y_base_vars = [f"s_{y_base}" for y_base in valid_y_bases]
        add_variables(model, y_base_vars, [0.0] * len(y_base_vars), "B")

        # Constraints
        # Constraints de no solapamiento
        cover_map = {}
        cons_rhs = 1

        for (a, b, t), cells in occupied_regions.items():
            var_name = f"z_{t}_{a}_{b}"
            for (x, y) in cells:
                cover_map.setdefault((x, y), set()).add(var_name)

        for (x, y), covering_vars in cover_map.items():
            coeffs = [1.0] * len(covering_vars)
            add_constraint_set(
                model,
                coeffs,
                covering_vars,
                cons_rhs,
                "L",
                added_constraints,
                f"consNoOverlap_{x}_{y}",
                DISABLE_DUPLICATE_CONSTRAINT_CHECK
            )

        # The slave internally chooses one vertical window of height
        # slice_height. Cada item seleccionado debe iniciar dentro de esa franja.
        if y_base_vars:
            add_constraint_set(
                model,
                [1.0] * len(y_base_vars),
                y_base_vars,
                1.0,
                "L",
                added_constraints,
                "consOneSliceWindow",
                DISABLE_DUPLICATE_CONSTRAINT_CHECK
            )

        for (a, b) in valid_x_positions:
            var_name = f"z_x_{a}_{b}"
            windows_containing_start = [
                f"s_{y_base}"
                for y_base in valid_y_bases
                if y_base <= b and b < y_base + slice_height
            ]
            add_constraint_set(
                model,
                [1.0] + [-1.0] * len(windows_containing_start),
                [var_name] + windows_containing_start,
                0.0,
                "L",
                added_constraints,
                f"consSliceWindow_x_{a}_{b}",
                DISABLE_DUPLICATE_CONSTRAINT_CHECK
            )

        for (a, b) in valid_y_positions:
            var_name = f"z_y_{a}_{b}"
            windows_containing_start = [
                f"s_{y_base}"
                for y_base in valid_y_bases
                if y_base <= b and b < y_base + slice_height
            ]
            add_constraint_set(
                model,
                [1.0] + [-1.0] * len(windows_containing_start),
                [var_name] + windows_containing_start,
                0.0,
                "L",
                added_constraints,
                f"consSliceWindow_y_{a}_{b}",
                DISABLE_DUPLICATE_CONSTRAINT_CHECK
            )

        print("OUT - Create Slave Model")
        return model
    except CplexSolverError:
        raise


def solve_slave_model(model, queue, manual_interruption, bin_width, item_height, item_width, slice_height):
    print("IN - Solve Slave Model")

    eps_second_phase = 1e-8

    def extract_current_solution(model):
        names = model.variables.get_names()
        values = model.solution.get_values()

        built_items = []
        active_variables = []

        for name, value in zip(names, values):
            if value <= 0.5:
                continue

            if name.startswith("z_x_") or name.startswith("z_y_"):
                active_variables.append(name)

            parts = name.split("_")
            if len(parts) != 4:
                continue

            _, tipo, a, b = parts
            a = int(a)
            b = int(b)

            if tipo == "x":
                item = Item(
                    height=item_height,
                    width=item_width,
                    rotated=False
                )
            else:
                item = Item(
                    height=item_width,
                    width=item_height,
                    rotated=True
                )

            item.set_position_x(a)
            item.set_position_y(b)
            built_items.append(item)

        if not built_items:
            return None, [], [], None

        positions_occupied = build_occupied_positions(
            names,
            values,
            item_height,
            item_width
        )

        slice_ = Slice(
            height=slice_height,
            width=bin_width,
            items=built_items
        )

        return slice_, built_items, active_variables, (names, values)

    def calculate_original_objective_for_solution(names, values, original_coeffs):
        fo = 0.0
        for name, value in zip(names, values):
            if value > 0.5:
                fo += original_coeffs.get(name, 0.0)
        return fo

    def print_summary(label, fo_original, built_items):
        rotated_count = sum(1 for item in built_items if item.get_rotated())
        no_rotated_count = len(built_items) - rotated_count
        summary = sorted(
            (item.get_position_x(), item.get_position_y(), item.get_rotated())
            for item in built_items
        )
        print(f"{label}")
        print(f"  FO original: {fo_original}")
        print(f"  Item count: {len(built_items)}")
        print(f"  Rotated: {rotated_count} | Non-rotated: {no_rotated_count}")
        print(f"  Items: {summary}")

    # =========================================================
    # PHASE 1: solve the original objective
    # =========================================================
    model.solve()

    status_string = model.solution.get_status_string()
    if "optimal" not in status_string.lower() and "feasible" not in status_string.lower():
        print("No feasible slave solution found")
        print("OUT - Solve Slave Model")
        return None, None, []

    phase_1_objective_value = model.solution.get_objective_value()
    print(f"Slave objective phase 1: {phase_1_objective_value}")

    names_vars = model.variables.get_names()
    linear_obj = model.objective.get_linear()
    original_coeffs = {name: coef for name, coef in zip(names_vars, linear_obj)}

    phase_1_slice, phase_1_items, phase_1_active_variables, phase_1_raw_solution = extract_current_solution(model)

    if phase_1_slice is None:
        print("No item was reconstructed in phase 1")
        print("OUT - Solve Slave Model")
        return None, phase_1_objective_value, []

    print_summary("Phase 1 summary", phase_1_objective_value, phase_1_items)

    if not USE_PRACTICAL_CG_ENHANCEMENTS:
        print("Practical CG enhancements disabled. Keeping phase 1 solution.")
        print("OUT - Solve Slave Model")
        return phase_1_slice, phase_1_objective_value, phase_1_active_variables

    # =========================================================
    # PHASE 2: optional structural improvement attempt
    # Keep the original objective almost unchanged and maximize item count
    # =========================================================
    try:
        rhs = phase_1_objective_value - eps_second_phase

        model.linear_constraints.add(
            lin_expr=[cplex.SparsePair(ind=names_vars, val=linear_obj)],
            senses=["G"],
            rhs=[rhs],
            names=["consMaintainOriginalObjective"]
        )

        # Reset objective
        model.objective.set_linear([(name, 0.0) for name in names_vars])

        # New objective: maximize active z variables
        model.objective.set_linear([
            (name, 1.0)
            for name in names_vars
            if name.startswith("z_x_") or name.startswith("z_y_")
        ])
        model.objective.set_sense(model.objective.sense.maximize)

        model.solve()

        phase_2_status_string = model.solution.get_status_string()
        if "optimal" in phase_2_status_string.lower() or "feasible" in phase_2_status_string.lower():
            phase_2_slice, phase_2_items, phase_2_active_variables, phase_2_raw_solution = extract_current_solution(model)

            if phase_2_slice is not None:
                phase_2_names, phase_2_values = phase_2_raw_solution
                phase_2_original_objective = calculate_original_objective_for_solution(
                    phase_2_names,
                    phase_2_values,
                    original_coeffs
                )

                print_summary("Phase 2 summary", phase_2_original_objective, phase_2_items)

                use_phase_2 = (
                    phase_2_original_objective >= phase_1_objective_value - eps_second_phase
                    and len(phase_2_items) > len(phase_1_items)
                )

                if use_phase_2:
                    print("Using phase 2 solution")
                    print("OUT - Solve Slave Model")
                    return phase_2_slice, phase_1_objective_value, phase_2_active_variables
                else:
                    print("Keeping phase 1 solution")
            else:
                print("Phase 2 did not reconstruct valid items. Keeping phase 1.")
        else:
            print("Phase 2 has no feasible solution. Keeping phase 1.")

    except Exception as e:
        print(f"Phase 2 failed: {e}. Keeping phase 1.")

    print("OUT - Solve Slave Model")
    return phase_1_slice, phase_1_objective_value, phase_1_active_variables
