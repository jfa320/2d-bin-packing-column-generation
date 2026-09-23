"""Backward-compatible facade for model construction and execution helpers.

New code should import from ``cplex_helpers``, ``solver_errors`` or
``model_runner`` according to its responsibility.  The facade remains so the
comparative models and external scripts do not need a flag-day migration.
"""

from utils.cplex_helpers import add_constraint, add_constraint_set, add_variables
from utils.execution_result import ExecutionResult
from utils.model_runner import run_model, solve_mip_model
from utils.paver_constants import PaverConstants
from utils.solver_errors import handle_solver_error
from utils.status_normalizer import map_cplex_mip_status

PAVER = PaverConstants

__all__ = [
    "add_constraint", "add_constraint_set", "add_variables",
    "ExecutionResult", "PAVER", "handle_solver_error", "run_model",
    "solve_mip_model", "map_cplex_mip_status",
]
