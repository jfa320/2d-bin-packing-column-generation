import cplex
from cplex.exceptions import CplexSolverError
import multiprocessing
import time
from utils.model_functions import *
from config import *

MODEL_NAME = "AndradeBirginBigM"


def apply_instance(instance):
    global CASE_NAME, BIN_WIDTH, BIN_HEIGHT, ITEM_WIDTH, ITEM_HEIGHT
    CASE_NAME = instance["case_name"]
    BIN_WIDTH = instance["bin_width"]
    BIN_HEIGHT = instance["bin_height"]
    ITEM_WIDTH = instance["item_width"]
    ITEM_HEIGHT = instance["item_height"]


def calculate_physical_item_bound():
    return (BIN_WIDTH * BIN_HEIGHT) // (ITEM_WIDTH * ITEM_HEIGHT)


def create_model(max_time):
    model = cplex.Cplex()

    model.set_results_stream(None)
    model.set_problem_type(cplex.Cplex.problem_type.MILP)
    model.objective.set_sense(model.objective.sense.maximize)
    model.parameters.timelimit.set(max_time)

    max_item_dim = max(ITEM_WIDTH, ITEM_HEIGHT)

    big_m_x = 2 * BIN_WIDTH + 2 * max_item_dim
    big_m_y = 2 * BIN_HEIGHT + 2 * max_item_dim
    items = list(range(1, calculate_physical_item_bound() + 1))

    # -----------------------------
    # Variables
    # -----------------------------
    used_var_names = [f"f_{i}" for i in items]
    used_var_obj = [1.0] * len(items)
    add_variables(model, used_var_names, used_var_obj, "B")

    rot_var_names = [f"r_{i}" for i in items]
    rot_var_obj = [0.0] * len(items)
    add_variables(model, rot_var_names, rot_var_obj, "B")

    center_var_names = [f"cx_{i}" for i in items] + [f"cy_{i}" for i in items]
    center_var_obj = [0.0] * len(center_var_names)
    add_variables(model, center_var_names, center_var_obj, "C")

    effective_dim_var_names = [f"wEff_{i}" for i in items] + [f"hEff_{i}" for i in items]
    effective_dim_var_obj = [0.0] * len(effective_dim_var_names)
    add_variables(model, effective_dim_var_names, effective_dim_var_obj, "C")

    relative_pos_vars = []
    for i in items:
        for j in items:
            if i < j:
                relative_pos_vars.append(f"q_{i},{j}")
                relative_pos_vars.append(f"q_{j},{i}")

    add_variables(model, relative_pos_vars, [0.0] * len(relative_pos_vars), "B")

    # -----------------------------
    # Effective dimensions
    # -----------------------------
    delta = ITEM_HEIGHT - ITEM_WIDTH

    for i in items:
        # wEff_i = ITEM_WIDTH + delta * r_i
        cons_coeff = [1.0, -delta]
        cons_vars = [f"wEff_{i}", f"r_{i}"]
        cons_rhs = ITEM_WIDTH
        cons_sense = "E"
        add_constraint(model, cons_coeff, cons_vars, cons_rhs, cons_sense)

        # hEff_i = ITEM_HEIGHT - delta * r_i
        cons_coeff = [1.0, delta]
        cons_vars = [f"hEff_{i}", f"r_{i}"]
        cons_rhs = ITEM_HEIGHT
        cons_sense = "E"
        add_constraint(model, cons_coeff, cons_vars, cons_rhs, cons_sense)

    # -----------------------------
    # Bin containment
    # -----------------------------
    for i in items:
        # cx_i - wEff_i / 2 >= 0
        cons_coeff = [1.0, -0.5]
        cons_vars = [f"cx_{i}", f"wEff_{i}"]
        cons_rhs = 0.0
        cons_sense = "G"
        add_constraint(model, cons_coeff, cons_vars, cons_rhs, cons_sense)

        # cx_i + wEff_i / 2 <= BIN_WIDTH
        cons_coeff = [1.0, 0.5]
        cons_vars = [f"cx_{i}", f"wEff_{i}"]
        cons_rhs = BIN_WIDTH
        cons_sense = "L"
        add_constraint(model, cons_coeff, cons_vars, cons_rhs, cons_sense)

        # cy_i - hEff_i / 2 >= 0
        cons_coeff = [1.0, -0.5]
        cons_vars = [f"cy_{i}", f"hEff_{i}"]
        cons_rhs = 0.0
        cons_sense = "G"
        add_constraint(model, cons_coeff, cons_vars, cons_rhs, cons_sense)

        # cy_i + hEff_i / 2 <= BIN_HEIGHT
        cons_coeff = [1.0, 0.5]
        cons_vars = [f"cy_{i}", f"hEff_{i}"]
        cons_rhs = BIN_HEIGHT
        cons_sense = "L"
        add_constraint(model, cons_coeff, cons_vars, cons_rhs, cons_sense)

    # -----------------------------
    # Non-overlap
    # -----------------------------
    for i in items:
        for j in items:
            if i < j:
                q_ij = f"q_{i},{j}"
                q_ji = f"q_{j},{i}"

                # 1) i to the right of j
                cons_coeff = [
                    1.0, -1.0,
                    -0.5, -0.5,
                    big_m_x, big_m_x
                ]
                cons_vars = [
                    f"cx_{i}", f"cx_{j}",
                    f"wEff_{i}", f"wEff_{j}",
                    q_ij, q_ji
                ]
                cons_rhs = 0.0
                cons_sense = "G"
                add_constraint(model, cons_coeff, cons_vars, cons_rhs, cons_sense)

                # 2) j to the right of i
                cons_coeff = [
                    1.0, -1.0,
                    -0.5, -0.5,
                    -big_m_x, -big_m_x
                ]
                cons_vars = [
                    f"cx_{j}", f"cx_{i}",
                    f"wEff_{i}", f"wEff_{j}",
                    q_ij, q_ji
                ]
                cons_rhs = -2 * big_m_x
                cons_sense = "G"
                add_constraint(model, cons_coeff, cons_vars, cons_rhs, cons_sense)

                # 3) i above j
                cons_coeff = [
                    1.0, -1.0,
                    -0.5, -0.5,
                    -big_m_y, big_m_y
                ]
                cons_vars = [
                    f"cy_{i}", f"cy_{j}",
                    f"hEff_{i}", f"hEff_{j}",
                    q_ij, q_ji
                ]
                cons_rhs = -big_m_y
                cons_sense = "G"
                add_constraint(model, cons_coeff, cons_vars, cons_rhs, cons_sense)

                # 4) j above i
                cons_coeff = [
                    1.0, -1.0,
                    -0.5, -0.5,
                    big_m_y, -big_m_y
                ]
                cons_vars = [
                    f"cy_{j}", f"cy_{i}",
                    f"hEff_{i}", f"hEff_{j}",
                    q_ij, q_ji
                ]
                cons_rhs = -big_m_y
                cons_sense = "G"
                add_constraint(model, cons_coeff, cons_vars, cons_rhs, cons_sense)

    return model


def solve_model(model, queue, manual_interruption):
    manual_interruption.value = False
    initial_time = time.time()

    try:
        model.solve()
        solver_time = time.time() - initial_time

        status = model.solution.get_status()
        status_string = model.solution.get_status_string(status)

        has_solution = model.solution.is_primal_feasible()

        if has_solution:
            objective_value = model.solution.get_objective_value()
        else:
            objective_value = "n/a"

        print("-------------------------------------------")
        print("Andrade-Birgin model with Big-M")
        print(f"Optimal value: {objective_value}")

        model_status = "1"
        solver_status = "1"

        if status == 105:
            print("The solver stopped because it reached the time limit.")
            model_status = "2"

        queue.put({
            "modelStatus": model_status,
            "solverStatus": solver_status,
            "objectiveValue": objective_value,
            "solverTime": solver_time
        })

    except CplexSolverError as e:
        solver_time = time.time() - initial_time
        print(f"CplexSolverError: {e}")

        queue.put({
            "modelStatus": "14",
            "solverStatus": "4",
            "objectiveValue": "n/a",
            "solverTime": solver_time
        })


def run_model(create_model_fn, solve_model_fn, queue, manual_interruption, max_time, instance=None):
    try:
        if instance is not None:
            apply_instance(instance)
        model = create_model_fn(max_time)
        solve_model_fn(model, queue, manual_interruption)
    except Exception as e:
        print(f"Error while running model: {e}")
        queue.put({
            "modelStatus": "14",
            "solverStatus": "4",
            "objectiveValue": "n/a",
            "solverTime": max_time
        })


def execute_with_time_limit(max_time, instance=None):
    global model_status, solver_status, objective_value, solver_time
    global exceding_limit_time

    exceding_limit_time = False

    queue = multiprocessing.Queue()
    manual_interruption = multiprocessing.Value('b', True)

    if instance is None:
        instance = get_instance(CASE_NAME)

    process = multiprocessing.Process(
        target=run_model,
        args=(create_model, solve_model, queue, manual_interruption, max_time, instance)
    )

    process.start()
    initial_time = time.time()

    while process.is_alive():
        if manual_interruption.value and time.time() - initial_time > max_time:
            print("Limit time reached. Aborting process.")
            model_status = "14"
            solver_status = "4"
            solver_time = max_time
            exceding_limit_time = True
            process.terminate()
            process.join()
            break
        time.sleep(0.1)

    while not queue.empty():
        message = queue.get()
        if isinstance(message, dict):
            print(message)
            model_status = message["modelStatus"]
            solver_status = message["solverStatus"]
            objective_value = message["objectiveValue"]
            solver_time = message["solverTime"]

    if exceding_limit_time:
        print("The model exceeded the execution time limit.")
        objective_value = "n/a"
        model_status = "14"

    return instance["case_name"], MODEL_NAME, model_status, solver_status, objective_value, solver_time
