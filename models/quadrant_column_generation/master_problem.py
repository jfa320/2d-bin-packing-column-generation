"""Restricted LP master and explicit duals for Marenco's quadrant model.

max sum(|s| * lambda[k,s]), subject to quadrant and global normal-point
coverage rows <= 1, with lambda >= 0 and NO individual finite upper bound.
CPLEX returns nonnegative row duals for this maximization/<= convention:
min sum(sigma) + sum(pi), with sigma[k] + sum(pi[p], p in P(s)) >= |s|.
Prices are returned unchanged, without negation or absolute values.

Only a supplied configuration pool is optimized. There is no pricing,
integer master, convergence test, or column-generation loop in this module.
Import explicitly so the geometry package remains independent from CPLEX.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from numbers import Real
from time import perf_counter
from typing import Iterable, Mapping

import cplex

from utils.paver_constants import PaverConstants
from utils.status_normalizer import NormalizedSolverStatus, map_cplex_lp_status
from .configuration import QuadrantConfiguration
from .discretization import GlobalDiscretization
from .quadrants import Quadrant


@dataclass(frozen=True)
class MasterDualPrices:
    sigma: dict[int, float]
    pi: dict[tuple[int, int], float]
    model_revision: int


@dataclass(frozen=True)
class RestrictedMasterResult:
    objective_value: float | None
    lambdas: dict[str, float]
    status: NormalizedSolverStatus
    proven_optimal: bool
    duals: MasterDualPrices | None
    solve_time_s: float
    model_revision: int
    raw_cplex_status: int | None = None
    error_message: str | None = None


def _finite_value(value):
    if (not isinstance(value, Real) or isinstance(value, bool)
            or not math.isfinite(value) or abs(value) >= cplex.infinity):
        raise ValueError("CPLEX returned a non-finite LP value")
    return float(value)


def _optimal(status):
    return (
        status.has_feasible_solution
        and status.model_status == PaverConstants.MODEL_STATUS_OPTIMAL
        and status.termination_status == PaverConstants.TERMINATION_NORMAL
    )


class MasterDualExtractor:
    """Retrieve each family by its explicit row map, never by parsed labels.

    An optimal, primal-valid LP is required. Empty coverage rows are included
    in pi, normally with price zero. Dual allocations can be nonunique.
    """

    def extract(
        self, model, quadrant_rows: Mapping[int, str],
        coverage_rows: Mapping[tuple[int, int], str], *, model_revision: int,
    ) -> MasterDualPrices:
        status = map_cplex_lp_status(
            model.solution.get_status(), model.solution.is_primal_feasible(),
        )
        if not _optimal(status):
            raise RuntimeError("duals require an optimal, primal-valid LP")

        def prices(rows):
            values = model.solution.get_dual_values(list(rows.values()))
            if len(values) != len(rows):
                raise ValueError("CPLEX returned an incomplete dual vector")
            return {key: _finite_value(value) for key, value in zip(rows, values)}

        return MasterDualPrices(prices(quadrant_rows), prices(coverage_rows), model_revision)


class RestrictedMasterModel:
    """Persistent LP; append configurations, then solve again for fresh duals.

    Exact duplicate configurations reuse their variable. Identical placements
    assigned to different quadrants remain different columns. Results carry
    a revision; adding a new column invalidates current dual availability.
    An unsuccessful CPLEX update requires rebuilding this model.
    """

    def __init__(self, model, discretization, quadrants, quadrant_rows, coverage_rows):
        self.cplex_model = model
        self.discretization = discretization
        self._quadrants = {q.index: q for q in quadrants}
        self._quadrant_rows = quadrant_rows
        self._coverage_rows = coverage_rows
        self._configurations = []
        self._variable_names = []
        self._name_by_configuration = {}
        self._counts = {k: 0 for k in self._quadrants}
        self._revision = 0
        self._last_result = None
        self._closed = False
        self._update_failed = False

    @property
    def configurations(self):
        return tuple(self._configurations)

    @property
    def variable_names(self):
        return tuple(self._variable_names)

    @property
    def quadrant_rows(self):
        return dict(self._quadrant_rows)

    @property
    def coverage_rows(self):
        return dict(self._coverage_rows)

    @property
    def model_revision(self):
        return self._revision

    def _require_usable(self):
        if self._closed:
            raise RuntimeError("restricted master is closed")
        if self._update_failed:
            raise RuntimeError("incremental update failed; rebuild the restricted master")

    def add_configuration(self, configuration: QuadrantConfiguration) -> str:
        self._require_usable()
        if not isinstance(configuration, QuadrantConfiguration):
            raise TypeError("expected a QuadrantConfiguration")
        k = configuration.quadrant.index
        if self._quadrants.get(k) != configuration.quadrant:
            raise ValueError("configuration quadrant does not match this master")
        # Phase A validates geometric feasibility; global membership is a
        # separate invariant and must be checked before changing the model.
        covered = set()
        for placement in configuration.placements:
            covered.update(self.discretization.covered_points(placement))
        if configuration in self._name_by_configuration:
            return self._name_by_configuration[configuration]

        name = f"lambda_{k}_{self._counts[k]}"
        row_names = [self._quadrant_rows[k]] + [
            self._coverage_rows[point] for point in sorted(covered)
        ]
        self._last_result = None
        try:
            self.cplex_model.variables.add(
                names=[name], obj=[float(configuration.item_count)], lb=[0.0],
                ub=[cplex.infinity],
                columns=[cplex.SparsePair(ind=row_names, val=[1.0] * len(row_names))],
                # Omit types: CPLEX defaults to continuous and preserves LP.
            )
        except Exception:
            self._update_failed = True
            raise
        self._configurations.append(configuration)
        self._variable_names.append(name)
        self._name_by_configuration[configuration] = name
        self._counts[k] += 1
        self._revision += 1
        return name

    def solve(self) -> RestrictedMasterResult:
        self._require_usable()
        self._last_result = None
        raw_status = None
        started = perf_counter()
        try:
            self.cplex_model.solve()
        except Exception as error:
            return self._error_result(error, perf_counter() - started, raw_status)
        elapsed = perf_counter() - started
        try:
            solution = self.cplex_model.solution
            raw_status = solution.get_status()
            status = map_cplex_lp_status(raw_status, solution.is_primal_feasible())
            objective, lambdas = None, {}
            if status.has_feasible_solution:
                objective = _finite_value(solution.get_objective_value())
                values = solution.get_values(self._variable_names) if self._variable_names else ()
                if len(values) != len(self._variable_names):
                    raise ValueError("CPLEX returned an incomplete primal vector")
                lambdas = {
                    name: _finite_value(value) for name, value in zip(self._variable_names, values)
                }
            proven = _optimal(status)
            duals = (
                MasterDualExtractor().extract(
                    self.cplex_model, self._quadrant_rows, self._coverage_rows,
                    model_revision=self._revision,
                ) if proven else None
            )
            result = RestrictedMasterResult(
                objective, lambdas, status, proven, duals, elapsed, self._revision,
                raw_cplex_status=raw_status,
                error_message=(
                    f"CPLEX status {raw_status} normalized to Error"
                    if status.termination_status == PaverConstants.TERMINATION_ERROR else None
                ),
            )
            self._last_result = result
            return result
        except Exception as error:
            return self._error_result(error, elapsed, raw_status)

    def _error_result(self, error, elapsed, raw_status):
        result = RestrictedMasterResult(
            None, {}, map_cplex_lp_status(None), False, None, elapsed, self._revision,
            raw_cplex_status=raw_status, error_message=f"{type(error).__name__}: {error}",
        )
        self._last_result = result
        return result

    def extract_duals(self) -> MasterDualPrices:
        """Return prices only for the latest optimal solve of the current LP."""
        self._require_usable()
        result = self._last_result
        if (result is None or result.model_revision != self._revision
                or result.duals is None):
            raise RuntimeError("solve the current restricted master optimally before extracting duals")
        return MasterDualPrices(dict(result.duals.sigma), dict(result.duals.pi), self._revision)

    def close(self):
        if not self._closed:
            self.cplex_model.end()
            self._closed = True
            self._last_result = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()


class RestrictedMasterBuilder:
    """Create all four quadrant rows and every coverage row in I x J upfront."""

    def __init__(self, discretization: GlobalDiscretization, quadrants: Iterable[Quadrant]):
        self.discretization = discretization
        self.quadrants = tuple(quadrants)
        if (len(self.quadrants) != 4
                or not all(isinstance(q, Quadrant) for q in self.quadrants)
                or {q.index for q in self.quadrants} != {1, 2, 3, 4}):
            raise ValueError("four applicable quadrants Q1..Q4 are required")
        if any(not (0 <= q.x_min < q.x_max <= discretization.bin_width
                    and 0 <= q.y_min < q.y_max <= discretization.bin_height)
               for q in self.quadrants):
            raise ValueError("quadrants must lie inside the global pallet")

    def build(
        self, configurations: Iterable[QuadrantConfiguration] = (), *, time_limit_s: float = 60.0,
    ) -> RestrictedMasterModel:
        if (not isinstance(time_limit_s, Real) or isinstance(time_limit_s, bool)
                or not math.isfinite(time_limit_s) or time_limit_s <= 0):
            raise ValueError("time_limit_s must be positive and finite")
        quadrant_rows = {k: f"quadrant_{k}" for k in range(1, 5)}
        coverage_rows = {
            (i, j): f"cover_{i}_{j}"
            for i in sorted(self.discretization.I) for j in sorted(self.discretization.J)
        }
        model = cplex.Cplex()
        try:
            model.set_log_stream(None)
            model.set_results_stream(None)
            model.set_warning_stream(None)
            model.set_problem_type(model.problem_type.LP)
            model.objective.set_sense(model.objective.sense.maximize)
            model.parameters.timelimit.set(float(time_limit_s))
            model.parameters.lpmethod.set(model.parameters.lpmethod.values.primal)
            names = list(quadrant_rows.values()) + list(coverage_rows.values())
            model.linear_constraints.add(
                lin_expr=[cplex.SparsePair(ind=[], val=[]) for _ in names],
                names=names, senses=["L"] * len(names), rhs=[1.0] * len(names),
            )
            master = RestrictedMasterModel(
                model, self.discretization, self.quadrants, quadrant_rows, coverage_rows,
            )
            for configuration in configurations:
                master.add_configuration(configuration)
            return master
        except BaseException:
            model.end()
            raise
