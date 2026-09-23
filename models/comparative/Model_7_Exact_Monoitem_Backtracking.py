"""Timed execution adapter for the exact mono-item backtracking algorithm."""

import time

from config import CASE_NAME, get_instance
from models.comparative.exact_monoitem_solver import (
    _can_place, _candidate_points, _generate_regular_grid, _normalize_by_gcd,
    _orientations, _overlap, _search_packing, _validate_dimensions,
    solve_exact_monoitem_2dbpp,
)
from utils.execution_result import ExecutionResult
from utils.execution_runner import TimedModelExecutor
from utils.paver_constants import PaverConstants

MODEL_NAME = "BacktrackingMonoitemExacto"
PAVER = PaverConstants


def _solve_in_process(queue, max_time, instance):
    started = time.perf_counter()
    try:
        result = solve_exact_monoitem_2dbpp(
            instance["bin_width"], instance["bin_height"],
            instance["item_width"], instance["item_height"],
            allow_rotation=True, max_time=max_time,
        )
        queue.put(ExecutionResult(
            instance["case_name"], MODEL_NAME, PAVER.MODEL_STATUS_OPTIMAL,
            PAVER.TERMINATION_NORMAL, float(result["capacity"]),
            time.perf_counter() - started,
        ))
    except TimeoutError:
        queue.put(ExecutionResult(
            instance["case_name"], MODEL_NAME, PAVER.MODEL_STATUS_NO_SOLUTION,
            PAVER.TERMINATION_TIME_LIMIT, None,
            time.perf_counter() - started,
        ))
    except Exception as error:
        queue.put(ExecutionResult(
            instance["case_name"], MODEL_NAME, None, PAVER.TERMINATION_ERROR,
            None, time.perf_counter() - started, error_message=str(error),
        ))


_EXECUTOR = TimedModelExecutor(
    _solve_in_process, MODEL_NAME, get_instance, lambda: CASE_NAME
)


def execute_with_time_limit(max_time, instance=None) -> ExecutionResult:
    return _EXECUTOR.execute_with_time_limit(max_time, instance)


if __name__ == "__main__":
    print(execute_with_time_limit(1200))
