"""Read pricing alternatives without changing the master or its certificates.

This module deliberately does not solve or populate a model. Callers must read
the current pool before changing its objective, and own all search budgets.
"""

from dataclasses import dataclass, field
import math


class InvalidPoolSolution(ValueError):
    """A reported solution violates the pricing/column mapping contract."""


@dataclass(frozen=True)
class PricingPoolOptions:
    """Opt-in settings. One column disables all pool-specific operations."""

    max_columns: int = 5
    mode: str = "passive"
    capacity: int = 20
    intensity: int | None = None
    populate_limit: int = 20
    populate_time_s: float = 1.0
    populate_ratio: float = 1.0

    def __post_init__(self):
        if self.mode not in {"passive", "populate"}:
            raise ValueError("Pool mode must be passive or populate")
        for name in ("max_columns", "capacity", "populate_limit"):
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                raise ValueError(f"{name} must be a positive integer")
        if self.intensity is not None and (
                isinstance(self.intensity, bool) or not isinstance(self.intensity, int)
                or self.intensity not in range(5)):
            raise ValueError("intensity must be an integer from 0 to 4")
        for name in ("populate_time_s", "populate_ratio"):
            value = getattr(self, name)
            if not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
                raise ValueError(f"{name} must be finite and positive")

    def configure(self, model):
        intensity = self.intensity
        if intensity is None:
            intensity = 1 if self.mode == "passive" else 2
        model.parameters.mip.pool.intensity.set(intensity)
        model.parameters.mip.pool.capacity.set(self.capacity)


def candidate_to_slice(candidate, geometry):
    """Allocate domain IDs only after a new candidate has been accepted."""
    from objects import Item, Slice

    return Slice(height=geometry.slice_height, width=geometry.bin_width, items=[
        Item(width=geometry.item_width if rotation == "x" else geometry.item_height,
             height=geometry.item_height if rotation == "x" else geometry.item_width,
             rotated=rotation == "y", position_x=x, position_y=y)
        for x, y, rotation in candidate.placements])


@dataclass(frozen=True)
class PricingGeometry:
    bin_width: int
    bin_height: int
    item_width: int
    item_height: int
    slice_height: int


@dataclass(frozen=True)
class PoolCandidate:
    placements: tuple
    cells: tuple
    value: float

    @property
    def master_key(self):
        return len(self.placements), self.cells


@dataclass
class PoolRead:
    candidates: list = field(default_factory=list)
    raw_count: int = 0
    examined: int = 0
    empty: int = 0
    nonpositive: int = 0
    duplicate_master: int = 0
    duplicate_incumbent: int = 0
    duplicate_pool: int = 0
    useful_extra: int = 0
    limited: int = 0
    errors: list = field(default_factory=list)


def slice_master_key(slice_):
    """Identity visible to the master, including square-orientation aliases."""
    cells = set()
    items = slice_.get_items()
    for item in items:
        x, y = item.get_position()
        cells.update((a, b)
                     for a in range(x, x + item.get_width())
                     for b in range(y, y + item.get_height()))
    return len(items), tuple(sorted(cells))


def candidate_from_values(names, values, duals, geometry, *,
                          coefficients=None, reported_objective=None):
    """Validate geometry and recompute the original objective with current duals."""
    if len(names) != len(values):
        raise InvalidPoolSolution("Variable names and values have different lengths")
    placements, occupied = [], set()
    pi = duals["pi"]
    for name, value in zip(names, values):
        if (not math.isfinite(value) or abs(value - round(value)) > 1e-5
                or value < -1e-5 or value > 1 + 1e-5):
            raise InvalidPoolSolution(f"Nonbinary pricing value: {name}={value}")
        if name.startswith("s_"):
            continue
        parts = name.split("_")
        if len(parts) != 4 or parts[0] != "z" or parts[1] not in {"x", "y"}:
            raise InvalidPoolSolution(f"Unexpected pricing variable: {name}")
        if value <= 0.5:
            continue
        rotation, x, y = parts[1], int(parts[2]), int(parts[3])
        width, height = ((geometry.item_width, geometry.item_height)
                         if rotation == "x" else
                         (geometry.item_height, geometry.item_width))
        if not (0 <= x and x + width <= geometry.bin_width
                and 0 <= y and y + height <= geometry.bin_height):
            raise InvalidPoolSolution(f"Placement outside bin: {name}")
        cells = {(a, b) for a in range(x, x + width)
                 for b in range(y, y + height)}
        if cells & occupied:
            raise InvalidPoolSolution(f"Overlapping placement: {name}")
        occupied.update(cells)
        # A square has the same physical placement in either orientation.
        placements.append((x, y, rotation if width != height else "x"))
    if placements:
        ys = [placement[1] for placement in placements]
        if max(ys) - min(ys) >= geometry.slice_height:
            raise InvalidPoolSolution("Placements do not fit one slice window")
    value = len(placements) - math.fsum(
        pi.get(f"({x},{y})", 0.0) for x, y in occupied)
    if not math.isfinite(value):
        raise InvalidPoolSolution("Nonfinite current-dual objective")
    comparisons = [reported_objective]
    if coefficients is not None:
        if len(coefficients) != len(names):
            raise InvalidPoolSolution("Objective coefficients have different length")
        comparisons.append(math.fsum(c for c, v in zip(coefficients, values) if v > 0.5))
    for expected in comparisons:
        if expected is not None and (not math.isfinite(expected) or not math.isclose(
                value, expected, rel_tol=1e-7, abs_tol=1e-6)):
            raise InvalidPoolSolution(
                f"Current-dual objective {value} differs from pricing objective {expected}")
    return PoolCandidate(tuple(sorted(placements)), tuple(sorted(occupied)), value)


def read_solution_pool(model, duals, geometry, known_keys, incumbent, *,
                       max_extra=4, eps=1e-9):
    """Return distinct improving extras; read errors preserve the incumbent.

    Invalid geometry/objectives are correctness failures and propagate. Ordinary
    pool-access errors are diagnostic data, never evidence of LP convergence.
    This function allocates no Item/Slice IDs and mutates neither model nor pool.
    """
    if not isinstance(max_extra, int) or isinstance(max_extra, bool) or max_extra < 0:
        raise ValueError("max_extra must be a nonnegative integer")
    result = PoolRead()
    try:
        names = model.variables.get_names()
        coefficients = model.objective.get_linear()
        result.raw_count = model.solution.pool.get_num()
    except Exception as error:
        result.errors.append(str(error))
        return result
    seen = set()
    for index in range(result.raw_count):
        try:
            values = model.solution.pool.get_values(index)
            objective = model.solution.pool.get_objective_value(index)
        except Exception as error:
            result.errors.append(f"solution {index}: {error}")
            continue
        result.examined += 1
        candidate = candidate_from_values(
            names, values, duals, geometry, coefficients=coefficients,
            reported_objective=objective)
        if not candidate.placements:
            result.empty += 1
        elif candidate.value <= eps:
            result.nonpositive += 1
        elif candidate.master_key in known_keys:
            result.duplicate_master += 1
        elif incumbent is not None and candidate.master_key == incumbent.master_key:
            result.duplicate_incumbent += 1
        elif candidate.master_key in seen:
            result.duplicate_pool += 1
        else:
            seen.add(candidate.master_key)
            result.candidates.append(candidate)
    result.candidates.sort(key=lambda candidate: (-candidate.value, candidate.placements))
    result.useful_extra = len(result.candidates)
    result.limited = max(0, result.useful_extra - max_extra)
    result.candidates = result.candidates[:max_extra]
    return result


def collect_pricing_extras(model, duals, geometry, known_keys, incumbent_slice,
                           options, progress, primary_time_s, remaining_time):
    """Harvest before/after optional bounded populate, preserving main evidence."""
    from utils.cg_instrumentation import timed_component

    with timed_component(progress, "pool_extract"):
        incumbent = candidate_from_values(
            model.variables.get_names(), model.solution.get_values(), duals, geometry,
            coefficients=model.objective.get_linear(),
            reported_objective=model.solution.get_objective_value())
        first = read_solution_pool(model, duals, geometry, known_keys, incumbent,
                                   max_extra=options.capacity)
    reads = [first]
    candidates = {candidate.master_key: candidate for candidate in first.candidates}
    reserved = int(incumbent_slice is not None and
                   slice_master_key(incumbent_slice) not in known_keys)
    available = options.max_columns - reserved
    populate_error = None
    if options.mode == "populate" and len(candidates) < available:
        requested = min(options.populate_time_s, options.populate_ratio * primary_time_s,
                        remaining_time())
        if requested > 0:
            previous_limit = model.parameters.timelimit.get()
            progress.record_pool({"pool_calls": 1})
            try:
                model.parameters.mip.limits.populate.set(options.populate_limit)
                model.parameters.timelimit.set(requested)
                with timed_component(progress, "pool_search"):
                    model.populate_solution_pool()
                status = model.solution.get_status()
                progress.diagnostics.pool_raw_status = status
                if progress.current_iteration is not None:
                    progress.current_iteration.pool_raw_status = status
            except Exception as error:
                populate_error = f"populate: {error}"
            finally:
                model.parameters.timelimit.set(previous_limit)
            with timed_component(progress, "pool_extract"):
                second = read_solution_pool(model, duals, geometry, known_keys, incumbent,
                                            max_extra=options.capacity)
            reads.append(second)
            for candidate in second.candidates:
                candidates.setdefault(candidate.master_key, candidate)
    errors = [error for read in reads for error in read.errors]
    if populate_error:
        errors.append(populate_error)
    if errors:
        progress.diagnostics.pool_last_error = "; ".join(errors)
    ordered = sorted(candidates.values(), key=lambda c: (-c.value, c.placements))
    progress.record_pool(dict(
        pool_examined=sum(read.examined for read in reads),
        pool_useful_extra=len(ordered), pool_read_errors=len(errors),
        pool_empty=sum(read.empty for read in reads),
        pool_nonpositive=sum(read.nonpositive for read in reads),
        pool_duplicates=sum(read.duplicate_master + read.duplicate_incumbent
                            + read.duplicate_pool for read in reads),
        pool_limited=max(0, len(ordered) - available)))
    return ordered[:available]
