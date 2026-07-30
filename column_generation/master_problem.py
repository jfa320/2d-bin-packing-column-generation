import cplex
from cplex.exceptions import CplexSolverError
from Utils.model_functions import *
from Config import *
import time

MODEL_NAME = "Model5Master"
DISABLE_DUPLICATE_CONSTRAINT_CHECK = True


def calculate_occupied_positions(position, width, height):
        """
        Returns all positions occupied by an item at `position` with `width` x `height` dimensions.
        """
        x, y = position
        positions_occupied = set()
        for dx in range(width):
            for dy in range(height):
                positions_occupied.add((x + dx, y + dy))
        return positions_occupied

def create_master_model(max_time, slices, height_bin, width_bin, height_item, width_item, positions_xy_x, positions_xy_y):
    print("IN - Create Master Model")
    h = height_bin
    model_slices = slices
    positions = [(x, y) for x in range(width_bin) for y in range(height_bin)]

    try:
        # Create problem instance
        model = cplex.Cplex()
        model.set_problem_type(cplex.Cplex.problem_type.MILP) 
        model.parameters.timelimit.set(max_time)
        
        # Disable presolve
        model.parameters.preprocessing.presolve.set(0)
        # Use simplex to solve the model
        model.parameters.lpmethod.set(1)
        # Variables
        # Binary p_r variables
        p_r_names = [f"p_{r.get_id()}" for r in model_slices]
        coeffs_p_r = [r.get_total_items() for r in model_slices]
        print("======================================")
        print("MASTER OBJECTIVE COEFFICIENTS")
        print("======================================")
        def summarize_slice(slice_):
            return sorted((item.get_position_x(), item.get_position_y(), item.get_rotated()) for item in slice_.get_items())

        for r, name, coef in zip(model_slices, p_r_names, coeffs_p_r):
            print(f"{name} | id={r.get_id()} | totalItems={r.get_total_items()} | lenItems={len(r.get_items())} | summary={summarize_slice(r)}")
        
        add_variables(model, p_r_names, coeffs_p_r, model.variables.type.binary)


        p_r_by_id = {r.get_id(): f"p_{r.get_id()}" for r in model_slices}
    
        model.objective.set_sense(model.objective.sense.maximize)

        added_constraints = set()
        
        
        # # ----------------------------------------------------
        # Precompute cells occupied by each slice: Phi(r)
        cells_by_slice = {}
        for r in model_slices:
            occupied = set()
            for it in r.get_items():
                if it.get_position_x() is None or it.get_position_y() is None:
                    continue
                x, y = it.get_position()
                for dx in range(it.get_width()):
                    for dy in range(it.get_height()):
                        occupied.add((x + dx, y + dy))
            cells_by_slice[r.get_id()] = occupied


        # Constraint for positions occupied by slices
        for (a, b) in positions:
            slices_covering_position = [r for r in model_slices if (a, b) in cells_by_slice[r.get_id()]]
            if slices_covering_position:
                indexes = [f"p_{r.get_id()}" for r in slices_covering_position]
                coeffs = [1.0] * len(slices_covering_position)
                add_constraint_set(
                    model,
                    coeffs,
                    indexes,
                    1.0,
                    "L",
                    added_constraints,
                    f"consItem_{a}_{b}",
                    DISABLE_DUPLICATE_CONSTRAINT_CHECK
                )

        # print(f"Used slices: {R}")
        print("OUT - Create Master Model")
        return model
    
    except CplexSolverError:
        raise


def solve_master_model(model, queue, manual_interruption, relax_model, initial_time):
    print("IN - Solve Master Model")
    # Default values sent to PAVER
    model_status, solver_status, objective_value, solver_time = "1", "1", 0, 1
    
    try:    
            # Disable manual interruption here
        manual_interruption.value = False
        
        
        if(relax_model):
            print("Relaxing model...")
            model.set_problem_type(cplex.Cplex.problem_type.LP)
        else:
            print("MODEL NOT RELAXED - KEEPING MILP")
            model.set_problem_type(cplex.Cplex.problem_type.MILP)
        
        # Solve the model
        model.solve()
            
        objective_value = model.solution.get_objective_value()
        if not relax_model:
            rounded_objective_value = round(objective_value)
            if abs(objective_value - rounded_objective_value) <= 1e-6:
                objective_value = rounded_objective_value
        # Print results
        print("Optimal value:", objective_value)
        dual_values = None
        active_variables = []
        if(relax_model):
            # Get dual values
            dual_values = get_dual_values(model)
            # print("Dual values:", dualValues)    
            
            
        # Print active variable values
        for i, var_name in enumerate(model.variables.get_names()):
            value_variable = model.solution.get_values(var_name)
            if value_variable > 0.5:
                active_variables.append(var_name)

        status = model.solution.get_status()
        
        
        
        if status == 105:  # CPLEX code 105 = Time limit exceeded
            print("The solver stopped because it reached the time limit.")
            model_status = "2" # PAVER value for a local optimum

        if(not relax_model):
            final_time = time.time()
            solver_time = final_time - initial_time
            solver_time = round(solver_time, 2)
            # Send results through the queue only for the final non-relaxed solve
            queue.put({
                "modelStatus": model_status,
                "solverStatus": solver_status,
                "objectiveValue": objective_value,
                "solverTime": solver_time
            })
        # Get the constraint count
        
        print("OUT - Solve Master Model")
        return objective_value, dual_values, active_variables
    
    except CplexSolverError as e:
        handle_solver_error(e, queue, solver_time)
        
def get_dual_values(model):
    print("Extracting dual values...")

    p_star = {"pi": {}}

    dual_values = model.solution.get_dual_values()
    constraint_names = model.linear_constraints.get_names()

    for name, dual_value in zip(constraint_names, dual_values):
        if name.startswith("consItem_"):
            # name: consItem_a_b
            _, a, b = name.split("_")
            p_star["pi"][f"({a},{b})"] = dual_value

    return p_star


