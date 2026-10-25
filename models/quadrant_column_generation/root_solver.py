"""Sequential quadrant column generation at the root, with a shared deadline.

Every iteration prices all four quadrants against one immutable dual snapshot.
Only afterwards are new improving configurations appended to the persistent
LP. Certificates are local to an iteration/revision and never carried forward.
This module solves no integer master and implements no branching tree.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum
import math
from numbers import Real
from time import perf_counter
from types import MappingProxyType

from utils.paver_constants import PaverConstants
from .configuration import QuadrantConfiguration
from .discretization import GlobalDiscretization
from .master_problem import MasterDualPrices, RestrictedMasterBuilder, RestrictedMasterResult
from .pricing_problem import DEFAULT_REDUCED_COST_TOLERANCE, PricingResult, QuadrantPricing
from .quadrants import Quadrant


# One absolute tolerance for improvement, closure, nonzero-price counts and
# monotonicity. Pass it explicitly to every pricing call.
EPS = DEFAULT_REDUCED_COST_TOLERANCE


class CGStatus(str, Enum):
    CONVERGED = "CG_CONVERGED"
    INCONCLUSIVE = "CG_INCONCLUSIVE"


class _DeadlineExpired(RuntimeError):
    pass


class _DeadlinePricing(QuadrantPricing):
    """Preserve the pricing API while charging model construction to the budget."""

    def __init__(self, discretization, quadrant, remaining):
        super().__init__(discretization, quadrant)
        self._remaining = remaining

    def _build_model(self, time_limit_s, objective):
        model = super()._build_model(time_limit_s, objective)
        try:
            budget = self._remaining()
            if budget <= 0:
                raise _DeadlineExpired("pricing construction exhausted the global deadline")
            model.cplex_model.parameters.timelimit.set(budget)
            return model
        except BaseException:
            model.close()
            raise


@dataclass
class RootPricingRecord:
    quadrant: int
    master_revision: int
    time_limit_s: float
    result: PricingResult | None = None
    wall_time_s: float = 0.0
    improving: bool = False
    added: bool = False
    duplicate: bool = False
    error_message: str | None = None


@dataclass
class RootIteration:
    iteration: int
    master_revision: int
    pool_before: int
    pool_after: int
    rmp: RestrictedMasterResult | None = None
    sigma: dict[int, float] = field(default_factory=dict)
    nonzero_pi_count: int = 0
    pricings: list[RootPricingRecord] = field(default_factory=list)
    # "found" means improving candidates, including duplicates. All feasible
    # candidates, even non-improving ones, remain in the pricing results.
    columns_found: list[QuadrantConfiguration] = field(default_factory=list)
    columns_added: list[QuadrantConfiguration] = field(default_factory=list)
    duplicates: list[QuadrantConfiguration] = field(default_factory=list)
    rmp_time_limit_s: float = 0.0
    rmp_wall_time_s: float = 0.0
    pricing_wall_time_s: float = 0.0
    column_update_time_s: float = 0.0
    iteration_time_s: float = 0.0
    outcome: str = "CG_INCONCLUSIVE"
    stop_reason: str | None = None


@dataclass(frozen=True)
class RootCGResult:
    status: CGStatus
    stop_reason: str
    objective_value: float | None
    last_rmp: RestrictedMasterResult | None
    configurations: tuple[QuadrantConfiguration, ...]
    iterations: tuple[RootIteration, ...]
    master_revision: int
    lp_is_current: bool
    total_time_s: float
    had_timeouts: bool
    error_message: str | None = None

    @property
    def converged(self):
        return self.status == CGStatus.CONVERGED


def _finite(value):
    return isinstance(value, Real) and not isinstance(value, bool) and math.isfinite(value)


def _snapshot(rmp):
    """Detach mutable result maps before retaining a historical LP snapshot."""
    duals = rmp.duals
    return replace(rmp, lambdas=dict(rmp.lambdas), duals=(
        MasterDualPrices(dict(duals.sigma), dict(duals.pi), duals.model_revision)
        if duals is not None else None
    ))


def _certifies(record, sigma):
    result = record.result
    return (
        result is not None and record.error_message is None
        and result.error_message is None and result.closure_proven
        and result.sigma == sigma and result.reduced_cost_tolerance == EPS
        and result.status.termination_status != PaverConstants.TERMINATION_ERROR
        and result.status.model_status in {
            PaverConstants.MODEL_STATUS_OPTIMAL, PaverConstants.MODEL_STATUS_FEASIBLE,
            PaverConstants.MODEL_STATUS_NO_SOLUTION,
        }
        and _finite(result.reduced_cost_upper_bound)
        and result.reduced_cost_upper_bound <= EPS
        and (result.reduced_cost is None or result.reduced_cost <= EPS)
    )


def solve_root(
    discretization: GlobalDiscretization, quadrants: tuple[Quadrant, ...], *,
    time_limit_s: float = 60.0,
) -> RootCGResult:
    """Start with four empty configurations and solve the root LP by CG.

    The deadline covers this entire call, including construction and updates.
    Before each solve, pass the remaining budget; check the deadline again
    after each blocking call. CPLEX limits are cooperative, so native-call and
    cleanup overhead can exceed the deadline; a late result never certifies
    convergence. No worker threads or subprocesses are started here.

    objective_value is the last optimal RMP value. lp_is_current is False if
    columns were subsequently added and the deadline prevented reoptimization.
    """
    if not _finite(time_limit_s) or time_limit_s < 0:
        raise ValueError("time_limit_s must be nonnegative and finite")
    started = perf_counter()
    deadline = started + float(time_limit_s)
    builder = RestrictedMasterBuilder(discretization, quadrants)
    ordered = tuple(sorted(builder.quadrants, key=lambda q: q.index))
    pool = [QuadrantConfiguration(q) for q in ordered]
    known = set(pool)
    history = []
    master, last_rmp, current = None, None, None
    revision = 0
    status, reason = CGStatus.INCONCLUSIVE, "global_deadline"
    error = None
    had_timeouts = False
    iteration_started = None

    def remaining():
        return max(0.0, deadline - perf_counter())

    try:
        budget = remaining()
        if budget > 0:
            master = builder.build(pool, time_limit_s=budget)
            revision = master.model_revision
        while master is not None and remaining() > 0:
            iteration_started = perf_counter()
            current = RootIteration(len(history) + 1, revision, len(pool), len(pool))
            history.append(current)
            budget = remaining()
            if budget <= 0:
                break
            # The master is already built: its construction/update time has
            # consumed budget before this timelimit is set.
            master.cplex_model.parameters.timelimit.set(budget)
            current.rmp_time_limit_s = budget
            phase_started = perf_counter()
            rmp = master.solve()
            current.rmp_wall_time_s = perf_counter() - phase_started
            current.rmp = _snapshot(rmp)
            had_timeouts |= rmp.status.termination_status == PaverConstants.TERMINATION_TIME_LIMIT
            if (not rmp.proven_optimal or rmp.error_message or rmp.duals is None
                    or not _finite(rmp.objective_value)
                    or rmp.model_revision != revision
                    or rmp.duals.model_revision != revision):
                reason = "rmp_not_optimal_or_invalid"
                break
            if last_rmp is not None and rmp.objective_value < last_rmp.objective_value - EPS:
                reason = "rmp_objective_decreased"
                break
            last_rmp = current.rmp
            sigma = MappingProxyType(dict(last_rmp.duals.sigma))
            pi = MappingProxyType(dict(last_rmp.duals.pi))
            if set(sigma) != {1, 2, 3, 4}:
                reason = "invalid_dual_snapshot"
                break
            current.sigma = dict(sigma)
            current.nonzero_pi_count = sum(abs(value) > EPS for value in pi.values())

            # No master mutation is allowed inside this loop. pi is the same
            # read-only mapping object in all four sequential calls.
            for quadrant in ordered:
                budget = remaining()
                if budget <= 0:
                    break
                record = RootPricingRecord(quadrant.index, revision, budget)
                current.pricings.append(record)
                phase_started = perf_counter()
                try:
                    result = _DeadlinePricing(discretization, quadrant, remaining).solve(
                        sigma[quadrant.index], pi, time_limit_s=budget,
                        reduced_cost_tolerance=EPS,
                    )
                    record.result = result
                    had_timeouts |= result.status.termination_status == PaverConstants.TERMINATION_TIME_LIMIT
                    if (result.sigma != sigma[quadrant.index]
                            or result.reduced_cost_tolerance != EPS):
                        raise ValueError("pricing result does not match the current dual snapshot/EPS")
                    if result.configuration is not None and result.configuration.quadrant != quadrant:
                        raise ValueError("pricing returned a configuration from another quadrant")
                    record.improving = (
                        result.configuration is not None
                        and result.status.has_feasible_solution
                        and _finite(result.reduced_cost) and result.reduced_cost > EPS
                    )
                    if record.improving:
                        current.columns_found.append(result.configuration)
                except Exception as exc:
                    record.error_message = f"{type(exc).__name__}: {exc}"
                record.wall_time_s = perf_counter() - phase_started
                current.pricing_wall_time_s += record.wall_time_s

            if remaining() <= 0 or len(current.pricings) != 4:
                reason = "global_deadline"
                break
            if master.model_revision != revision:
                reason = "master_changed_during_pricing"
                break

            phase_started = perf_counter()
            for record in current.pricings:
                if not record.improving or record.error_message:
                    continue
                config = record.result.configuration
                if config in known:
                    record.duplicate = True
                    current.duplicates.append(config)
                    continue
                if remaining() <= 0:
                    break
                master.add_configuration(config)
                revision = master.model_revision
                known.add(config)
                pool.append(config)
                record.added = True
                current.columns_added.append(config)
            current.column_update_time_s = perf_counter() - phase_started
            current.pool_after = len(pool)
            if remaining() <= 0:
                reason = "global_deadline"
                break
            if current.columns_added:
                current.outcome = "COLUMNS_ADDED"
                current.stop_reason = "new_improving_columns"
                current.iteration_time_s = perf_counter() - iteration_started
                current = None
                # All certificates above referred to the previous revision.
                # The next iteration starts with an entirely fresh record.
                continue
            if current.columns_found:
                reason = "duplicate_improving_columns"
                break
            if all(_certifies(record, sigma[record.quadrant]) for record in current.pricings):
                status, reason = CGStatus.CONVERGED, "four_current_pricing_certificates"
                break
            reason = "pricing_inconclusive"
            break
    except Exception as exc:
        reason, error = "error", f"{type(exc).__name__}: {exc}"
    finally:
        if master is not None:
            revision = master.model_revision
            try:
                master.close()
            except Exception as exc:
                status, reason = CGStatus.INCONCLUSIVE, "cleanup_error"
                error = f"{type(exc).__name__}: {exc}"
        ended = perf_counter()
        if status == CGStatus.CONVERGED and ended >= deadline:
            status, reason = CGStatus.INCONCLUSIVE, "global_deadline"
        if current is not None:
            current.pool_after = len(pool)
            current.outcome = status.value
            current.stop_reason = reason
            current.iteration_time_s = ended - iteration_started
    had_timeouts |= reason == "global_deadline" or ended >= deadline
    return RootCGResult(
        status, reason, last_rmp.objective_value if last_rmp is not None else None,
        last_rmp, tuple(pool), tuple(history), revision,
        last_rmp is not None and last_rmp.model_revision == revision,
        ended - started, had_timeouts, error,
    )
