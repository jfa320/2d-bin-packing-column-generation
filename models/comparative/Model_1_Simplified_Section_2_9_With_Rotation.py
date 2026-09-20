import cplex
from utils.model_functions import *
from utils.execution_runner import TimedModelExecutor
from config import *

MODEL_NAME = "Model1Rotation"


def apply_instance(instance):
    global CASE_NAME, BIN_WIDTH, BIN_HEIGHT, ITEM_WIDTH, ITEM_HEIGHT
    CASE_NAME = instance["case_name"]
    BIN_WIDTH = instance["bin_width"]
    BIN_HEIGHT = instance["bin_height"]
    ITEM_WIDTH = instance["item_width"]
    ITEM_HEIGHT = instance["item_height"]


def run_model_for_instance(queue, max_time, instance):
    apply_instance(instance)
    run_model(create_model, solve_model, queue, max_time, CASE_NAME, MODEL_NAME)


def calculate_physical_item_bound():
    return (BIN_WIDTH * BIN_HEIGHT) // (ITEM_WIDTH * ITEM_HEIGHT)


def create_model(max_time):
    # Create a CPLEX model
    model = cplex.Cplex()
    model.set_results_stream(None)  # Disable detailed CPLEX logs
    model.set_problem_type(cplex.Cplex.problem_type.MILP)
    model.objective.set_sense(model.objective.sense.maximize)
    model.parameters.timelimit.set(max_time)

    # Define variables and objective
    items = list(range(1, calculate_physical_item_bound() + 1))
    item_quantity = len(items)
    vars_names = [f"f_{i}" for i in items]
    coeffs = [1.0] * item_quantity  # Assign coefficient 1 to each variable
    add_variables(model, vars_names, coeffs, "B")

    additional_vars_names = [f"x_{i}" for i in items] + [f"y_{i}" for i in items] + [f"r_{i}" for i in items]
    additional_coeff_obj = [0.0] * len(additional_vars_names)
    model.variables.add(
        names=additional_vars_names,
        obj=additional_coeff_obj,
        types="I" * (2 * item_quantity) + "B" * item_quantity
    )

    additional_vars_names = []
    for i in items:
        for j in items:
            if i != j:
                additional_vars_names.append(f"l_{i},{j}")  # l_{ij} variable
                additional_vars_names.append(f"b_{i},{j}")  # b_{ij} variable

    additional_coeff_obj = [0.0] * len(additional_vars_names)
    add_variables(model, additional_vars_names, additional_coeff_obj, "B")

    # Non-overlap constraints
    for i in items:
        for j in items:
            if i < j:
                cons_coeff = [1.0, 1.0, 1.0, 1.0, -1.0, -1.0]
                cons_vars = [f"l_{i},{j}", f"l_{j},{i}", f"b_{i},{j}", f"b_{j},{i}", f"f_{i}", f"f_{j}"]
                cons_rhs = -1.0
                cons_sense = "G"
                add_constraint(model, cons_coeff, cons_vars, cons_rhs, cons_sense)

    # Constraints x_i - x_j + W l_{ij} <= W - w (1 - r_i) - h r_i
    for i in items:
        for j in items:
            if i != j:
                cons_coeff = [1.0, -1.0, BIN_WIDTH, -ITEM_WIDTH + ITEM_HEIGHT]
                cons_vars = [f"x_{i}", f"x_{j}", f"l_{i},{j}", f"r_{i}"]
                cons_rhs = BIN_WIDTH - ITEM_WIDTH
                cons_sense = "L"
                add_constraint(model, cons_coeff, cons_vars, cons_rhs, cons_sense)

    # Constraints y_i - y_j + H b_{ij} <= H - h (1 - r_i) - w r_i
    for i in items:
        for j in items:
            if i != j:
                cons_coeff = [1.0, -1.0, BIN_HEIGHT, -ITEM_HEIGHT + ITEM_WIDTH]
                cons_vars = [f"y_{i}", f"y_{j}", f"b_{i},{j}", f"r_{i}"]
                cons_rhs = BIN_HEIGHT - ITEM_HEIGHT
                cons_sense = "L"
                add_constraint(model, cons_coeff, cons_vars, cons_rhs, cons_sense)

    # Constraints that keep objects inside the bin (considering rotation)
    for i in items:
        cons_x_coeff = [1.0, BIN_WIDTH, -ITEM_WIDTH + ITEM_HEIGHT]  # Coefficients for x_i, f_i, r_i
        cons_x_vars = [f"x_{i}", f"f_{i}", f"r_{i}"]
        cons_x_rhs = 2 * BIN_WIDTH - ITEM_WIDTH
        cons_x_sense = "L"
        add_constraint(model, cons_x_coeff, cons_x_vars, cons_x_rhs, cons_x_sense)

        cons_y_coeff = [1.0, BIN_HEIGHT, -ITEM_HEIGHT + ITEM_WIDTH]  # Coefficients for y_i, f_i, r_i
        cons_y_vars = [f"y_{i}", f"f_{i}", f"r_{i}"]
        cons_y_rhs = 2 * BIN_HEIGHT - ITEM_HEIGHT
        cons_y_sense = "L"
        add_constraint(model, cons_y_coeff, cons_y_vars, cons_y_rhs, cons_y_sense)

    return model


def solve_model(model):
    return solve_mip_model(model, CASE_NAME, MODEL_NAME)


_EXECUTOR = TimedModelExecutor(
    run_model_for_instance, MODEL_NAME, get_instance, lambda: CASE_NAME
)


def execute_with_time_limit(max_time, instance=None) -> ExecutionResult:
    return _EXECUTOR.execute_with_time_limit(max_time, instance)
