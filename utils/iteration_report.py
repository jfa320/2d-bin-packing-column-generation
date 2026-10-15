"""Solver-free CSV projections of CG iteration history and phase totals."""

from pathlib import Path


ITERATION_STATUS_PREFIXES = (
    "lp", "pricing", "pricing_phase2", "auxiliary_pricing",
    "auxiliary_pricing_phase2",
)
TIME_COMPONENTS = (
    "master_lp", "pricing", "master_build", "master_solve",
    "pricing_build", "pricing_solve",
)
ITERATION_VALUE_FIELDS = (
    "iteration", "completed", "pool_before", "pool_after",
    "generated_columns", "lp_value", "pricing_objective", "pricing_best_bound",
    "master_lp_time_s", "pricing_time_s", "master_build_time_s",
    "master_solve_time_s", "pricing_build_time_s", "pricing_solve_time_s",
    "iteration_time_s", "pricing_calls", "pricing_phase2_calls", "stop_reason",
)
ITERATION_OUTPUT_FIELDS = ("instance", "family") + ITERATION_VALUE_FIELDS + tuple(
    f"{phase}_{field}" for phase in ITERATION_STATUS_PREFIXES
    for field in ("model_status", "termination_status", "raw_cplex_status")
)
PHASE_OUTPUT_FIELDS = (
    "instance", "family", "cg_iterations", "iteration_records", "total_time_s",
    "cg_time_s", "integer_master_time_s",
) + tuple(f"{component}_time_s" for component in TIME_COMPONENTS) + tuple(
    f"{component}_percent_{denominator}"
    for component in TIME_COMPONENTS for denominator in ("total", "cg")
)


def report_paths(output):
    """Return sidecars alongside the principal report without changing its name."""
    output = Path(output)
    return (
        output.with_name(f"{output.stem}_iterations.csv"),
        output.with_name(f"{output.stem}_phases.csv"),
    )


def format_csv_value(value):
    """Use the same null and numeric formatting in all benchmark reports."""
    if value is None:
        return "NA"
    if isinstance(value, float):
        return f"{value:.6f}"
    return value


def iteration_rows(instance, result):
    """Yield one record per finalized attempt, including interrupted attempts.

    Completed CG iterations and recorded attempts can differ when a build or
    solve is interrupted. The execution layer finalizes such partial records
    in ``result.iterations``; ``current_iteration`` is internal snapshot data.
    """
    for iteration in result.iterations:
        values = {
            "instance": instance["instance"],
            "family": instance["family"],
            **{
                field: getattr(iteration, field)
                for field in ITERATION_VALUE_FIELDS
            },
        }
        for phase in ITERATION_STATUS_PREFIXES:
            status = getattr(iteration, f"{phase}_status")
            for field in ("model_status", "termination_status", "raw_cplex_status"):
                values[f"{phase}_{field}"] = getattr(status, field)
        yield values


def phase_row(instance, result):
    """Project cumulative times and percentages with both explicit denominators.

    Aggregate master/pricing percentages include build and solve work, so they
    overlap their component percentages and must not be added to those parts.
    A nonpositive denominator has no meaningful percentage and exports as NA.
    """
    metrics = result.metrics
    values = {
        "instance": instance["instance"],
        "family": instance["family"],
        "cg_iterations": metrics.cg_iterations,
        "iteration_records": len(result.iterations),
        "total_time_s": result.execution.total_time_s,
        "cg_time_s": metrics.cg_time_s,
        "integer_master_time_s": metrics.integer_master_time_s,
    }
    denominators = {"total": result.execution.total_time_s, "cg": metrics.cg_time_s}
    for component in TIME_COMPONENTS:
        value = getattr(metrics, f"{component}_time_s")
        values[f"{component}_time_s"] = value
        for name, denominator in denominators.items():
            values[f"{component}_percent_{name}"] = (
                100 * value / denominator if denominator > 0 else None
            )
    return values
