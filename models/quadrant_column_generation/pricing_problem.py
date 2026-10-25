"""One Beasley pricing solve for a quadrant and a fixed dual-price snapshot.

Placement coefficient: 1 - sum(pi[p] for p covered by the placement).
The MIP objective excludes sigma; both the incumbent and the MIP upper bound
are shifted by -sigma afterwards. A closure certificate applies ONLY to this
quadrant and these supplied prices, never to the full master or a CG loop.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import math
from numbers import Real
from time import perf_counter

import cplex

from utils.paver_constants import PaverConstants
from utils.status_normalizer import NormalizedSolverStatus, map_cplex_mip_status
from .beasley_model import BeasleyModelBuilder, BeasleyResult
from .configuration import QuadrantConfiguration
from .discretization import GlobalDiscretization
from .quadrants import Quadrant


DEFAULT_REDUCED_COST_TOLERANCE = 1e-9


@dataclass(frozen=True)
class PricingResult:
    configuration: QuadrantConfiguration | None
    pricing_objective: float | None
    reduced_cost: float | None
    status: NormalizedSolverStatus
    proven_optimal: bool
    best_bound: float | None
    reduced_cost_upper_bound: float | None
    solve_time_s: float
    total_time_s: float
    sigma: float
    reduced_cost_tolerance: float
    has_improving_column: bool = False
    closure_proven: bool = False
    closure_basis: str | None = None
    raw_cplex_status: int | None = None
    error_message: str | None = None


def _finite_number(value, name):
    if (not isinstance(value, Real) or isinstance(value, bool)
            or not math.isfinite(value) or abs(value) >= cplex.infinity):
        raise ValueError(f"{name} must be a finite real number")
    return float(value)


class QuadrantPricing:
    """Solve the complete placement universe of one quadrant, with no cuts.

    sigma is the scalar sigma[k]. pi may be sparse: omitted global points have
    price zero. Explicit keys must belong to I x J. Prices are copied for the
    solve and used unchanged (no sign inversion, stabilization, or clipping).
    The returned best_bound is in the unshifted Beasley objective's units.
    """

    def __init__(self, discretization: GlobalDiscretization, quadrant: Quadrant):
        self.discretization = discretization
        self.quadrant = quadrant

    def solve(
        self, sigma: float, pi: Mapping[tuple[int, int], float], *,
        time_limit_s: float = 60.0,
        reduced_cost_tolerance: float = DEFAULT_REDUCED_COST_TOLERANCE,
    ) -> PricingResult:
        sigma = _finite_number(sigma, "sigma")
        tolerance = _finite_number(reduced_cost_tolerance, "reduced_cost_tolerance")
        if tolerance < 0:
            raise ValueError("reduced_cost_tolerance must be nonnegative")
        time_limit_s = _finite_number(time_limit_s, "time_limit_s")
        if time_limit_s <= 0:
            raise ValueError("time_limit_s must be positive")
        if not isinstance(pi, Mapping):
            raise TypeError("pi must map global normal points to prices")
        prices = {}
        for point, value in pi.items():
            if (not isinstance(point, tuple) or len(point) != 2
                    or any(isinstance(x, bool) or not isinstance(x, int) for x in point)
                    or point[0] not in self.discretization.I
                    or point[1] not in self.discretization.J):
                raise ValueError("pi keys must belong to the global normal-point grid I x J")
            prices[point] = _finite_number(value, f"pi[{point}]")

        def coefficient(placement):
            return 1.0 - math.fsum(
                prices.get(point, 0.0)
                for point in self.discretization.covered_points(placement)
            )

        started = perf_counter()
        try:
            with self._build_model(time_limit_s, coefficient) as model:
                base = model.solve()
        except cplex.exceptions.CplexError as error:
            return self._failure(str(error), sigma, tolerance, started)
        try:
            return self._map_result(base, prices, sigma, tolerance, started)
        except ValueError as error:
            # Inconsistent incumbent telemetry cannot supply a feasible column
            # or a proof. Keep its raw solver code as diagnostic evidence.
            return self._failure(
                str(error), sigma, tolerance, started,
                solve_time_s=base.solve_time_s, raw_status=base.raw_cplex_status,
            )

    def _build_model(self, time_limit_s, objective):
        """Internal hook for a caller enforcing a deadline after construction."""
        return BeasleyModelBuilder(self.discretization, self.quadrant).build(
            time_limit_s=time_limit_s, objective=objective,
        )

    def _map_result(self, base: BeasleyResult, prices, sigma, tolerance, started):
        configuration, objective, reduced_cost = None, None, None
        if base.status.has_feasible_solution:
            objective = _finite_number(base.objective_value, "pricing objective")
            configuration = QuadrantConfiguration(self.quadrant, base.placements)
            covered = set()
            for placement in configuration.placements:
                covered.update(self.discretization.covered_points(placement))
            reconstructed = configuration.item_count - math.fsum(
                prices.get(point, 0.0) for point in covered
            )
            if not math.isclose(objective, reconstructed, rel_tol=1e-9, abs_tol=1e-7):
                raise ValueError("Beasley objective disagrees with configuration coverage")
            reduced_cost = _finite_number(objective - sigma, "reduced cost")

        best_bound = (
            _finite_number(base.best_bound, "Beasley best bound")
            if base.best_bound is not None else None
        )
        if (objective is not None and best_bound is not None
                and best_bound < objective
                and not math.isclose(best_bound, objective, rel_tol=1e-9, abs_tol=1e-7)):
            raise ValueError("Beasley upper bound is below its incumbent")
        usable_evidence = (
            base.error_message is None
            and base.status.termination_status != PaverConstants.TERMINATION_ERROR
            and base.status.model_status in {
                PaverConstants.MODEL_STATUS_OPTIMAL,
                PaverConstants.MODEL_STATUS_FEASIBLE,
                PaverConstants.MODEL_STATUS_NO_SOLUTION,
            }
        )
        proven_optimal = (
            usable_evidence and base.proven_optimal and configuration is not None
            and base.status.model_status == PaverConstants.MODEL_STATUS_OPTIMAL
            and base.status.termination_status == PaverConstants.TERMINATION_NORMAL
        )
        reduced_bound = None
        if usable_evidence and best_bound is not None:
            reduced_bound = _finite_number(best_bound - sigma, "reduced cost upper bound")
        elif proven_optimal:
            # Optimality itself supplies an upper bound if the MIP bound query
            # was unavailable. best_bound remains None, as reported by Beasley.
            reduced_bound = reduced_cost

        improving = reduced_cost is not None and reduced_cost > tolerance
        basis = None
        if not improving and usable_evidence:
            if proven_optimal and reduced_cost <= tolerance:
                basis = "optimal_pricing"
            elif reduced_bound is not None and reduced_bound <= tolerance:
                basis = "pricing_upper_bound"
        return PricingResult(
            configuration, objective, reduced_cost, base.status, proven_optimal,
            best_bound, reduced_bound, base.solve_time_s, perf_counter() - started,
            sigma, tolerance, has_improving_column=improving,
            closure_proven=basis is not None, closure_basis=basis,
            raw_cplex_status=base.raw_cplex_status, error_message=base.error_message,
        )

    @staticmethod
    def _failure(message, sigma, tolerance, started, *, solve_time_s=0.0, raw_status=None):
        return PricingResult(
            None, None, None, map_cplex_mip_status(None), False, None, None,
            solve_time_s, perf_counter() - started, sigma, tolerance,
            raw_cplex_status=raw_status, error_message=message,
        )
