"""Model solving and worker lifecycle, independent from model construction."""

import time

from utils.execution_result import ExecutionResult
from utils.paver_constants import PaverConstants
from utils.status_normalizer import map_cplex_mip_status

PAVER = PaverConstants


def solve_mip_model(model, case_name, model_name):
    model.solve()
    raw_status = model.solution.get_status()
    status = map_cplex_mip_status(raw_status, model.solution.is_primal_feasible())
    objective = (
        float(model.solution.get_objective_value())
        if status.has_feasible_solution else None
    )
    return ExecutionResult(
        case_name, model_name, status.model_status, status.termination_status,
        objective, 0.0, raw_cplex_status=raw_status,
        error_message=(
            f"CPLEX status {raw_status} normalized to Error."
            if status.termination_status == PAVER.TERMINATION_ERROR else None
        ),
    )


def run_model(create_model, solve_model, queue, max_time, case_name, model_name):
    start = time.perf_counter()
    model = None
    result = ExecutionResult(
        case_name, model_name, None, PAVER.TERMINATION_ERROR, None, 0.0
    )
    try:
        model = create_model(max_time)
        remaining = max_time - (time.perf_counter() - start)
        if remaining <= 0:
            result = ExecutionResult(
                case_name, model_name, PAVER.MODEL_STATUS_NO_SOLUTION,
                PAVER.TERMINATION_TIME_LIMIT, None, 0.0,
            )
        else:
            model.parameters.timelimit.set(remaining)
            result = solve_model(model)
    except Exception as exc:
        result = ExecutionResult(
            case_name, model_name, None, PAVER.TERMINATION_ERROR, None, 0.0,
            error_message=str(exc),
        )
    finally:
        if model is not None:
            try:
                model.end()
            except Exception as exc:
                result.termination_status = PAVER.TERMINATION_ERROR
                result.error_message = "; ".join(filter(None, [
                    result.error_message, f"Model cleanup failed: {exc}",
                ]))
    result.total_time_s = time.perf_counter() - start
    queue.put(result)
