import cplex
import time
from utils.model_functions import *
from utils.execution_runner import execute_in_process
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


def solve_model(model):
    return solve_mip_model(model, CASE_NAME, MODEL_NAME)


def run_model_for_instance(queue, max_time, instance):
    apply_instance(instance)
    run_model(create_model, solve_model, queue, max_time, CASE_NAME, MODEL_NAME)


def execute_with_time_limit(max_time, instance=None) -> ExecutionResult:
    start = time.perf_counter()
    if instance is None:
        instance = get_instance(CASE_NAME)
    return execute_in_process(run_model_for_instance, max_time, instance, MODEL_NAME, start)
