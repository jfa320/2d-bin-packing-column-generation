"""Translate CPLEX codes without exposing them as model/termination statuses."""

from dataclasses import dataclass
from typing import Optional

from utils.paver_constants import PaverConstants


PAVER = PaverConstants


@dataclass(frozen=True)
class NormalizedSolverStatus:
    model_status: Optional[int]
    termination_status: str
    has_feasible_solution: bool


# Entries are (model status, termination reason, implied primal feasibility).
_MIP = {
    101: (PAVER.MODEL_STATUS_OPTIMAL, PAVER.TERMINATION_NORMAL, True),
    102: (PAVER.MODEL_STATUS_FEASIBLE, PAVER.TERMINATION_NORMAL, True),
    103: (PAVER.MODEL_STATUS_NO_SOLUTION_RETURNED, PAVER.TERMINATION_NORMAL, False),
    104: (PAVER.MODEL_STATUS_FEASIBLE, PAVER.TERMINATION_OTHER_LIMIT, True),
    105: (PAVER.MODEL_STATUS_FEASIBLE, PAVER.TERMINATION_NODE_LIMIT, True),
    106: (PAVER.MODEL_STATUS_NO_SOLUTION, PAVER.TERMINATION_NODE_LIMIT, False),
    107: (PAVER.MODEL_STATUS_FEASIBLE, PAVER.TERMINATION_TIME_LIMIT, True),
    108: (PAVER.MODEL_STATUS_NO_SOLUTION, PAVER.TERMINATION_TIME_LIMIT, False),
    109: (PAVER.MODEL_STATUS_FEASIBLE, PAVER.TERMINATION_ERROR, True),
    110: (PAVER.MODEL_STATUS_ERROR, PAVER.TERMINATION_ERROR, False),
    111: (PAVER.MODEL_STATUS_FEASIBLE, PAVER.TERMINATION_OTHER_LIMIT, True),
    112: (PAVER.MODEL_STATUS_NO_SOLUTION, PAVER.TERMINATION_OTHER_LIMIT, False),
    113: (PAVER.MODEL_STATUS_FEASIBLE, PAVER.TERMINATION_OTHER, True),
    114: (PAVER.MODEL_STATUS_NO_SOLUTION, PAVER.TERMINATION_OTHER, False),
    115: (PAVER.MODEL_STATUS_INTERMEDIATE_INFEASIBLE, PAVER.TERMINATION_NORMAL, False),
    116: (PAVER.MODEL_STATUS_FEASIBLE, PAVER.TERMINATION_ERROR, True),
    117: (PAVER.MODEL_STATUS_ERROR, PAVER.TERMINATION_ERROR, False),
    118: (PAVER.MODEL_STATUS_LOCALLY_OPTIMAL, PAVER.TERMINATION_NORMAL, False),
    119: (PAVER.MODEL_STATUS_SOLUTION_UNBOUNDED, PAVER.TERMINATION_NORMAL, False),
    127: (PAVER.MODEL_STATUS_FEASIBLE, PAVER.TERMINATION_OTHER, True),
    131: (PAVER.MODEL_STATUS_FEASIBLE, PAVER.TERMINATION_TIME_LIMIT, True),
    132: (PAVER.MODEL_STATUS_NO_SOLUTION, PAVER.TERMINATION_TIME_LIMIT, False),
    133: (PAVER.MODEL_STATUS_ERROR, PAVER.TERMINATION_OTHER, False),
}

_LP = {
    1: (PAVER.MODEL_STATUS_OPTIMAL, PAVER.TERMINATION_NORMAL, True),
    2: (PAVER.MODEL_STATUS_LOCALLY_OPTIMAL, PAVER.TERMINATION_NORMAL, False),
    3: (PAVER.MODEL_STATUS_INFEASIBLE, PAVER.TERMINATION_NORMAL, False),
    4: (PAVER.MODEL_STATUS_SOLUTION_UNBOUNDED, PAVER.TERMINATION_NORMAL, False),
    5: (PAVER.MODEL_STATUS_INTERMEDIATE_INFEASIBLE, PAVER.TERMINATION_NORMAL, False),
    6: (PAVER.MODEL_STATUS_INTERMEDIATE_INFEASIBLE, PAVER.TERMINATION_OTHER, False),
    10: (PAVER.MODEL_STATUS_INTERMEDIATE_INFEASIBLE, PAVER.TERMINATION_ITERATION_LIMIT, False),
    11: (PAVER.MODEL_STATUS_INTERMEDIATE_INFEASIBLE, PAVER.TERMINATION_TIME_LIMIT, False),
    12: (PAVER.MODEL_STATUS_INTERMEDIATE_INFEASIBLE, PAVER.TERMINATION_OTHER_LIMIT, False),
    13: (PAVER.MODEL_STATUS_INTERMEDIATE_INFEASIBLE, PAVER.TERMINATION_USER_INTERRUPT, False),
}


def _normalize(raw_status, has_feasible_solution, user_interrupted, table, feasible_status):
    if raw_status not in table:
        return NormalizedSolverStatus(PAVER.MODEL_STATUS_ERROR, PAVER.TERMINATION_ERROR, False)
    model_status, termination, implied_feasible = table[raw_status]
    # Invalid optimal points and proofs without a primal point never authorize
    # objective extraction, even if CPLEX reports a numerically feasible point.
    invalid_primal = raw_status in ({103, 110, 115, 117, 118, 119, 133} if table is _MIP else {2, 3, 4, 5})
    feasible = not invalid_primal and (
        implied_feasible if has_feasible_solution is None else bool(has_feasible_solution)
    )
    if not invalid_primal:
        if feasible:
            model_status = (model_status
                            if model_status == PAVER.MODEL_STATUS_OPTIMAL
                            else feasible_status)
        else:
            if implied_feasible and termination == PAVER.TERMINATION_NORMAL:
                termination = PAVER.TERMINATION_ERROR
            model_status = (PAVER.MODEL_STATUS_ERROR
                            if termination == PAVER.TERMINATION_ERROR
                            else (PAVER.MODEL_STATUS_NO_SOLUTION
                                  if table is _MIP else PAVER.MODEL_STATUS_INTERMEDIATE_INFEASIBLE))
    if user_interrupted and table is _MIP and raw_status in {113, 114}:
        termination = PAVER.TERMINATION_USER_INTERRUPT
    return NormalizedSolverStatus(model_status, termination, feasible)


def map_cplex_mip_status(
    raw_status: Optional[int],
    has_feasible_solution: Optional[bool] = None,
    user_interrupted: bool = False,
) -> NormalizedSolverStatus:
    return _normalize(
        raw_status, has_feasible_solution, user_interrupted,
        _MIP, PAVER.MODEL_STATUS_FEASIBLE,
    )


def map_cplex_lp_status(
    raw_status: Optional[int],
    has_feasible_solution: Optional[bool] = None,
    user_interrupted: bool = False,
) -> NormalizedSolverStatus:
    return _normalize(
        raw_status, has_feasible_solution, user_interrupted,
        _LP, PAVER.MODEL_STATUS_LP_FEASIBLE,
    )
