import cplex
from cplex.exceptions import CplexSolverError
import multiprocessing
import time
from utils.model_functions import *
from config import *

# Based on the simplified model 1 formulation (base model - Pisinger & Sigurd); see Overleaf section 2.8 for the complete model
# Simple case improved by rotation
MODEL_NAME = "Model1"


def apply_instance(instance):
    global CASE_NAME, BIN_WIDTH, BIN_HEIGHT, ITEM_WIDTH, ITEM_HEIGHT
    CASE_NAME = instance["case_name"]
    BIN_WIDTH = instance["bin_width"]
    BIN_HEIGHT = instance["bin_height"]
    ITEM_WIDTH = instance["item_width"]
    ITEM_HEIGHT = instance["item_height"]


def run_model_for_instance(instance, create_model_fn, solve_model_fn, queue, manual_interruption, max_time):
    apply_instance(instance)
    run_model(create_model_fn, solve_model_fn, queue, manual_interruption, max_time)


def calculate_physical_item_bound():
    return (BIN_WIDTH // ITEM_WIDTH) * (BIN_HEIGHT // ITEM_HEIGHT)


def create_model(max_time):
    # Create a CPLEX model
    model = cplex.Cplex()

    model.set_results_stream(None)  # Disable detailed CPLEX logs
    model.set_problem_type(cplex.Cplex.problem_type.MILP)
    model.objective.set_sense(model.objective.sense.maximize)
    # Set the execution time limit
    model.parameters.timelimit.set(max_time)

    # Define variables and objective
    items = list(range(1, calculate_physical_item_bound() + 1))
    vars_names = [f"f_{i}" for i in items]
    coeffs = [1.0] * len(items)
    add_variables(model, vars_names, coeffs, "B")

    additional_vars_names = [f"x_{i}" for i in items] + [f"y_{i}" for i in items]
    additional_coeff_obj = [0.0] * len(additional_vars_names)
    add_variables(model, additional_vars_names, additional_coeff_obj, "I")

    additional_vars_names = set()
    for i in items:
        for j in items:
            if i != j:
                additional_vars_names.add(f"l_{i},{j}")  # Add variable l_{ij}
                additional_vars_names.add(f"l_{j},{i}")  # Add variable l_{ij}
                additional_vars_names.add(f"b_{i},{j}")  # Add variable b_{ij}
                additional_vars_names.add(f"b_{j},{i}")  # Add variable b_{ij}
    additional_vars_names = list(additional_vars_names)
    additional_coeff_obj = [0.0] * len(additional_vars_names)
    add_variables(model, additional_vars_names, additional_coeff_obj, "B")

    # Add constraints for each pair (i, j) with i < j
    for i in items:
        for j in items:
            if i < j:  # This constraint had to be rewritten to work with CPLEX
                cons_coeff = [1.0, 1.0, 1.0, 1.0, -1.0, -1.0]
                cons_vars = [f"l_{i},{j}", f"l_{j},{i}", f"b_{i},{j}", f"b_{j},{i}", f"f_{i}", f"f_{j}"]
                cons_rhs = -1.0
                cons_sense = "G"  # "G" means >=
                add_constraint(model, cons_coeff, cons_vars, cons_rhs, cons_sense)

    # Add constraints x_i - x_j + W l_{ij} <= W - w for each i in I
    for i in items:
        for j in items:
            if i != j:
                cons_coeff = [1.0, -1.0, BIN_WIDTH]
                cons_vars = [f"x_{i}", f"x_{j}", f"l_{i},{j}"]
                cons_rhs = BIN_WIDTH - ITEM_WIDTH
                cons_sense = "L"  # "L" means <=
                add_constraint(model, cons_coeff, cons_vars, cons_rhs, cons_sense)

    # Add constraints y_i - y_j + H b_{ij} <= H - h for each i in I
    for i in items:
        for j in items:
            if i != j:
                cons_coeff = [1.0, -1.0, BIN_HEIGHT]
                cons_vars = [f"y_{i}", f"y_{j}", f"b_{i},{j}"]
                cons_rhs = BIN_HEIGHT - ITEM_HEIGHT
                cons_sense = "L"  # "L" means <=
                add_constraint(model, cons_coeff, cons_vars, cons_rhs, cons_sense)

    # Add constraint x_i + W f_i <= 2W - w for each i in I
    for i in items:
        cons_coeff = [1.0, BIN_WIDTH]  # Coefficients for x_i and f_i
        cons_vars = [f"x_{i}", f"f_{i}"]  # Variables in the constraint
        cons_rhs = 2 * BIN_WIDTH - ITEM_WIDTH  # Right-hand side of the constraint
        cons_sense = "L"  # "L" means <=
        add_constraint(model, cons_coeff, cons_vars, cons_rhs, cons_sense)

    # Add constraint y_i + H f_i <= 2H - h for each i in I
    for i in items:
        cons_coeff = [1.0, BIN_HEIGHT]  # Coefficients for y_i and f_i
        cons_vars = [f"y_{i}", f"f_{i}"]  # Variables in the constraint
        cons_rhs = 2 * BIN_HEIGHT - ITEM_HEIGHT  # Right-hand side of the constraint
        cons_sense = "L"  # "L" means <=
        add_constraint(model, cons_coeff, cons_vars, cons_rhs, cons_sense)

    return model


def solve_model(model, queue, manual_interruption):
    # Disable manual interruption here
    manual_interruption.value = False

    # Solve the model
    model.solve()

    # Get and print results
    objective_value = model.solution.get_objective_value()
    print("-------------------------------------------")
    print("Model 1 - No Rotation")
    print(f"Optimal value: {objective_value}")

    model_status, solver_status = "1", "1"
    status = model.solution.get_status()
    if status == 105:
        print("The solver stopped because it reached the time limit.")
        model_status = "2"

    return model_status, solver_status, objective_value


def execute_with_time_limit(max_time, instance=None):
    global model_status, solver_status, objective_value, solver_time
    global exceding_limit_time
    exceding_limit_time = False

    # Create a queue to receive subprocess results
    queue = multiprocessing.Queue()

    # Create a shared variable to handle manual interruption
    manual_interruption = multiprocessing.Value('b', True)

    if instance is None:
        instance = get_instance(CASE_NAME)

    # Create the subprocess that runs the function
    process = multiprocessing.Process(target=run_model_for_instance, args=(instance, create_model, solve_model, queue, manual_interruption, max_time))

    # Start the subprocess
    process.start()

    initial_time = time.time()

    # Monitor the queue while the process is running
    while process.is_alive():
        if manual_interruption.value and time.time() - initial_time > max_time:
            print("Limit time reached. Aborting process.")
            model_status = "14"  # PAVER value for a model that returned no answer because of an error
            solver_status = "4"  # The solver finished model execution
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
