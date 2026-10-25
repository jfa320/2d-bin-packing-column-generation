"""Isolated Beasley packing MIP for one quadrant (Marenco, Section 2).

Only placements and coverage incidences from the GLOBAL discretization are
used. The default objective counts rectangles. A coefficient callback is the
only objective extension point; this module knows nothing about master duals,
pricing, or column generation. Import it explicitly to keep Phase A solver-free.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from numbers import Real
from time import perf_counter
from types import MappingProxyType
from typing import Callable

import cplex

from utils.cplex_helpers import add_constraint, add_variables
from utils.paver_constants import PaverConstants
from utils.status_normalizer import NormalizedSolverStatus, map_cplex_mip_status
from .configuration import Placement
from .discretization import GlobalDiscretization
from .quadrants import Quadrant


@dataclass(frozen=True)
class BeasleyResult:
    """Result for one quadrant, with an incumbent only when primal-valid.

    For the default unit objective, objective_value equals len(placements).
    A custom objective reports its weighted value instead. proven_optimal
    requires a normal optimal status, not merely MIP optimality within a gap.
    """

    objective_value: float | None
    placements: tuple[Placement, ...]
    status: NormalizedSolverStatus
    proven_optimal: bool
    best_bound: float | None
    solve_time_s: float
    raw_cplex_status: int | None = None
    error_message: str | None = None


def _finite_value(value):
    if (isinstance(value, Real) and not isinstance(value, bool)
            and math.isfinite(value) and abs(value) < cplex.infinity):
        return float(value)
    return None


class BeasleyModel:
    """A built MIP with its variable-to-placement mapping and explicit lifetime.

    Use as a context manager or call ``close`` to release CPLEX resources.
    ``solve_time_s`` measures the CPLEX solve, excluding model construction.
    The best bound is an upper bound for THIS quadrant/objective only.
    """

    def __init__(self, model, placements, variable_names, objective_coefficients,
                 coverage_rows):
        self.cplex_model = model
        self.placements = placements
        self.variable_names = variable_names
        self.objective_coefficients = objective_coefficients
        self.coverage_rows = MappingProxyType(coverage_rows)
        self._closed = False

    def solve(self) -> BeasleyResult:
        if self._closed:
            raise RuntimeError("Beasley model is closed")
        started = perf_counter()
        raw_status = None
        try:
            self.cplex_model.solve()
        except Exception as error:
            return self._error_result(error, perf_counter() - started, raw_status)
        elapsed = perf_counter() - started
        try:
            solution = self.cplex_model.solution
            raw_status = solution.get_status()
            status = map_cplex_mip_status(raw_status, solution.is_primal_feasible())
            objective = None
            selected = ()
            if status.has_feasible_solution:
                objective = _finite_value(solution.get_objective_value())
                if objective is None:
                    raise ValueError("CPLEX returned a non-finite objective")
                values = solution.get_values(list(self.variable_names)) if self.variable_names else ()
                selected = tuple(
                    placement for placement, value in zip(self.placements, values)
                    if value > 0.5
                )
            proven_optimal = (
                status.has_feasible_solution
                and status.model_status == PaverConstants.MODEL_STATUS_OPTIMAL
                and status.termination_status == PaverConstants.TERMINATION_NORMAL
            )
            best_bound = None
            if (status.termination_status != PaverConstants.TERMINATION_ERROR
                    and status.model_status in {
                        PaverConstants.MODEL_STATUS_OPTIMAL,
                        PaverConstants.MODEL_STATUS_FEASIBLE,
                        PaverConstants.MODEL_STATUS_NO_SOLUTION,
                    }):
                try:
                    best_bound = _finite_value(solution.MIP.get_best_objective())
                except cplex.exceptions.CplexError:
                    # A missing bound does not invalidate a feasible incumbent.
                    pass
            return BeasleyResult(
                objective, selected, status, proven_optimal, best_bound, elapsed,
                raw_cplex_status=raw_status,
                error_message=(
                    f"CPLEX status {raw_status} normalized to Error"
                    if status.termination_status == PaverConstants.TERMINATION_ERROR
                    else None
                ),
            )
        except Exception as error:
            return self._error_result(error, elapsed, raw_status)

    @staticmethod
    def _error_result(error, elapsed, raw_status):
        return BeasleyResult(
            None, (), map_cplex_mip_status(None), False, None, elapsed,
            raw_cplex_status=raw_status,
            error_message=f"{type(error).__name__}: {error}",
        )

    def close(self):
        if not self._closed:
            self.cplex_model.end()
            self._closed = True

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()


class BeasleyModelBuilder:
    """Build placement binaries and normal-point set-packing constraints.

    ``objective`` maps a placement to a finite coefficient; None means 1 for
    every placement. Changing coefficients never changes the feasible set.
    Coverage uses points in I x J, via Phase A's covered_points definition.
    Coverage rows with no incident placements are tautologies and omitted.
    Redundant nonempty rows are retained with their original global indices.
    """

    def __init__(self, discretization: GlobalDiscretization, quadrant: Quadrant):
        self.discretization = discretization
        self.quadrant = quadrant

    def build(
        self, *, time_limit_s: float = 60.0,
        objective: Callable[[Placement], float] | None = None,
    ) -> BeasleyModel:
        if (not isinstance(time_limit_s, Real) or isinstance(time_limit_s, bool)
                or not math.isfinite(time_limit_s) or time_limit_s <= 0):
            raise ValueError("time_limit_s must be positive and finite")
        placements = self.discretization.placements_in(self.quadrant)
        coefficients = tuple(
            _finite_value(objective(p) if objective is not None else 1.0)
            for p in placements
        )
        if any(value is None for value in coefficients):
            raise ValueError("objective coefficients must be finite real numbers")
        names = tuple(
            f"{'y' if p.rotated else 'x'}_{p.x}_{p.y}" for p in placements
        )
        coverage = {}
        for index, placement in enumerate(placements):
            for point in self.discretization.covered_points(placement):
                coverage.setdefault(point, []).append(index)
        rows = {point: tuple(coverage[point]) for point in sorted(coverage)}

        model = cplex.Cplex()
        try:
            model.set_log_stream(None)
            model.set_results_stream(None)
            model.set_warning_stream(None)
            model.set_problem_type(model.problem_type.MILP)
            model.parameters.timelimit.set(float(time_limit_s))
            model.objective.set_sense(model.objective.sense.maximize)
            if names:
                add_variables(model, list(names), list(coefficients), "B")
            for (i, j), indices in rows.items():
                add_constraint(
                    model, [1.0] * len(indices), [names[index] for index in indices],
                    1.0, "L", f"cover_{i}_{j}",
                )
            return BeasleyModel(model, placements, names, coefficients, rows)
        except BaseException:
            model.end()
            raise
