"""Translate CPLEX codes without exposing them as model/termination statuses."""

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class NormalizedSolverStatus:
    model_status: Optional[int]
    termination_status: str
    has_feasible_solution: bool


# Entries are (model status, termination reason, implied primal feasibility).
_MIP = {
    101: (1, "Normal", True),
    102: (8, "Normal", True),
    103: (10, "Normal", False),
    104: (8, "OtherLimit", True),
    105: (8, "NodeLimit", True),
    106: (9, "NodeLimit", False),
    107: (8, "TimeLimit", True),
    108: (9, "TimeLimit", False),
    109: (8, "Error", True),
    110: (13, "Error", False),
    111: (8, "OtherLimit", True),
    112: (9, "OtherLimit", False),
    113: (8, "Other", True),
    114: (9, "Other", False),
    115: (6, "Normal", False),
    116: (8, "Error", True),
    117: (13, "Error", False),
    118: (18, "Normal", False),
    119: (12, "Normal", False),
    127: (8, "Other", True),
    131: (8, "TimeLimit", True),
    132: (9, "TimeLimit", False),
    133: (13, "Other", False),
}

_LP = {
    1: (1, "Normal", True),
    2: (18, "Normal", False),
    3: (4, "Normal", False),
    4: (12, "Normal", False),
    5: (6, "Normal", False),
    6: (6, "Other", False),
    10: (6, "IterationLimit", False),
    11: (6, "TimeLimit", False),
    12: (6, "OtherLimit", False),
    13: (6, "UserInterrupt", False),
}


def _normalize(raw_status, has_feasible_solution, user_interrupted, table, feasible_status):
    if raw_status not in table:
        return NormalizedSolverStatus(13, "Error", False)
    model_status, termination, implied_feasible = table[raw_status]
    # Invalid optimal points and proofs without a primal point never authorize
    # objective extraction, even if CPLEX reports a numerically feasible point.
    invalid_primal = raw_status in ({103, 110, 115, 117, 118, 119, 133} if table is _MIP else {2, 3, 4, 5})
    feasible = not invalid_primal and (
        implied_feasible if has_feasible_solution is None else bool(has_feasible_solution)
    )
    if not invalid_primal:
        if feasible:
            model_status = model_status if model_status == 1 else feasible_status
        else:
            if implied_feasible and termination == "Normal":
                termination = "Error"
            model_status = 13 if termination == "Error" else (9 if table is _MIP else 6)
    if user_interrupted and table is _MIP and raw_status in {113, 114}:
        termination = "UserInterrupt"
    return NormalizedSolverStatus(model_status, termination, feasible)


def map_cplex_mip_status(
    raw_status: Optional[int],
    has_feasible_solution: Optional[bool] = None,
    user_interrupted: bool = False,
) -> NormalizedSolverStatus:
    return _normalize(raw_status, has_feasible_solution, user_interrupted, _MIP, 8)


def map_cplex_lp_status(
    raw_status: Optional[int],
    has_feasible_solution: Optional[bool] = None,
    user_interrupted: bool = False,
) -> NormalizedSolverStatus:
    return _normalize(raw_status, has_feasible_solution, user_interrupted, _LP, 7)
