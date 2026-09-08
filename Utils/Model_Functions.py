import cplex
import time
from utils.execution_result import ExecutionResult
from utils.status_normalizer import map_cplex_mip_status


def add_variables(model, var_names, obj_coeffs, var_type):
    n = len(var_names)
    types = [var_type] * n

    lb = [0.0] * n
    if var_type == "B":
        ub = [1.0] * n
    else:
        ub = [cplex.infinity] * n

    model.variables.add(
        names=var_names,
        obj=obj_coeffs,
        lb=lb,
        ub=ub,
        types=types
    )


def add_constraint(model, coeff, vars, rhs, sense, constraint_name=None):
    if constraint_name:
        model.linear_constraints.add(
            lin_expr=[cplex.SparsePair(vars, coeff)],
            senses=[sense],
            rhs=[rhs],
            names=[constraint_name]
        )
    else:
        model.linear_constraints.add(
            lin_expr=[cplex.SparsePair(vars, coeff)],
            senses=[sense],
            rhs=[rhs]
        )


def add_constraint_set(
    model,
    coeff,
    vars,
    rhs,
    sense,
    added_constraints,
    constraint_name=None,
    disable_duplicate_constraint_check=False
):
    filtered = [(c, v) for c, v in zip(coeff, vars) if c != 0]
    if filtered:
        coeff, vars = zip(*filtered)
    else:
        coeff, vars = (), ()

    new_constraint = (tuple(coeff), tuple(vars), rhs, sense)

    if new_constraint in added_constraints and not disable_duplicate_constraint_check:
        return

    if vars:
        add_constraint(model, coeff, vars, rhs, sense, constraint_name)
        added_constraints.add(new_constraint)


def handle_solver_error(e, queue, solver_time):
    # Retain the dictionary envelope used by reference models and CG callers.
    queue.put({
        "modelStatus": "14",
        "solverStatus": "10",
        "objectiveValue": None,
        "solverTime": solver_time,
        "error_message": str(e),
    })


def solve_mip_model(model, case_name, model_name):
    model.solve()
    raw_status = model.solution.get_status()
    status = map_cplex_mip_status(raw_status, model.solution.is_primal_feasible())
    objective = float(model.solution.get_objective_value()) if status.has_feasible_solution else None
    return ExecutionResult(
        case_name, model_name, status.model_status, status.termination_status,
        objective, 0.0, raw_cplex_status=raw_status,
        error_message=(f"CPLEX status {raw_status} normalized to Error."
                       if status.termination_status == "Error" else None),
    )


def run_model(create_model, solve_model, queue, max_time, case_name, model_name):
    start = time.perf_counter()
    model = None
    result = ExecutionResult(case_name, model_name, None, "Error", None, 0.0)
    try:
        model = create_model(max_time)
        remaining = max_time - (time.perf_counter() - start)
        if remaining <= 0:
            result = ExecutionResult(case_name, model_name, 9, "TimeLimit", None, 0.0)
        else:
            model.parameters.timelimit.set(remaining)
            result = solve_model(model)
    except Exception as exc:
        result = ExecutionResult(case_name, model_name, None, "Error", None, 0.0, error_message=str(exc))
    finally:
        if model is not None:
            try:
                model.end()
            except Exception as exc:
                result.termination_status = "Error"
                result.error_message = "; ".join(filter(None, [
                    result.error_message, f"Model cleanup failed: {exc}",
                ]))
    result.total_time_s = time.perf_counter() - start
    queue.put(result)
