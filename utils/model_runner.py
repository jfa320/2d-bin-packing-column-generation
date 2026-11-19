"""Model solving and worker lifecycle, independent from model construction."""

import math
import time

from utils.execution_result import ExecutionResult, MIPIncumbent
from utils.paver_constants import PaverConstants
from utils.status_normalizer import map_cplex_lp_status, map_cplex_mip_status

PAVER = PaverConstants


def solve_mip_model(model, case_name, model_name):
    return _solve_cplex_model(model, case_name, model_name, map_cplex_mip_status)


def solve_lp_model(model, case_name, model_name):
    model.set_problem_type(model.problem_type.LP)
    return _solve_cplex_model(model, case_name, model_name, map_cplex_lp_status)


def _solve_cplex_model(model, case_name, model_name, normalize_status):
    model.solve()
    raw_status = model.solution.get_status()
    status = normalize_status(raw_status, model.solution.is_primal_feasible())
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


def _report_mip_incumbents(model, queue):
    from cplex.callbacks import MIPInfoCallback

    maximize = model.objective.get_sense() == model.objective.sense.maximize

    class IncumbentReporter(MIPInfoCallback):
        best_objective = -math.inf if maximize else math.inf

        def __call__(self):
            if not self.has_incumbent():
                return
            objective = self.get_incumbent_objective_value()
            improved = (objective > self.best_objective if maximize
                        else objective < self.best_objective)
            if improved and math.isfinite(objective):
                queue.put(MIPIncumbent(objective))
                self.best_objective = objective

    model.register_callback(IncumbentReporter)


def run_model(create_model, solve_model, queue, max_time, case_name, model_name,
              *, report_mip_incumbents=False, random_seed=None, threads=None):
    start = time.perf_counter()
    model = None
    result = ExecutionResult(
        case_name, model_name, None, PAVER.TERMINATION_ERROR, None, 0.0
    )
    try:
        model = create_model(max_time)
        if random_seed is not None:
            model.parameters.randomseed.set(random_seed)
        if threads is not None:
            model.parameters.threads.set(threads)
        if report_mip_incumbents:
            _report_mip_incumbents(model, queue)
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
