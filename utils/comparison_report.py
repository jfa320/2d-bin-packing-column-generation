"""Project solver results into the LP and integer benchmark views."""

import math
from pathlib import Path

from utils.paver_constants import PaverConstants as PAVER


COMMON_FIELDS = (
    "instance", "family", "bin_width", "bin_height", "item_width", "item_height",
    "optimal_literature", "source",
    "model", "run_mode", "value", "value_kind", "time_s", "time_basis",
    "model_status", "termination_status", "stop_reason", "raw_cplex_status",
    "run_termination_status", "error_message", "max_time_s", "random_seed",
    "threads", "settings",
)
LP_FIELDS = COMMON_FIELDS + (
    "lp_primal_value", "rmp_value", "rmp_raw_cplex_status",
    "lp_convergence_proven", "convergence_basis",
)
INTEGER_FIELDS = COMMON_FIELDS + ("integer_master_time_s",)


def comparison_paths(output):
    output = Path(output)
    return tuple(output.with_name(f"{output.stem}_{axis}.csv")
                 for axis in ("lp", "integer"))


def _finite(value):
    return value if value is not None and math.isfinite(value) else None


def comparator_row(result, mode):
    objective = _finite(result.objective_value)
    optimal = (objective is not None and result.model_status == PAVER.MODEL_STATUS_OPTIMAL
               and result.termination_status == PAVER.TERMINATION_NORMAL
               and result.error_message is None)
    value = objective
    kind = "unavailable"
    row = {}
    if mode == "lp":
        value = objective if optimal else None
        row["lp_primal_value"] = objective if not optimal else None
        if objective is not None:
            kind = "certified_lp" if optimal else "lp_primal"
    elif objective is not None:
        kind = "optimal" if optimal else "incumbent"
    return dict(
        row, model=result.model_name, run_mode=mode, value=value, value_kind=kind,
        time_s=result.total_time_s, time_basis="end_to_end",
        model_status=result.model_status, termination_status=result.termination_status,
        stop_reason=result.termination_status, raw_cplex_status=result.raw_cplex_status,
        run_termination_status=result.termination_status, error_message=result.error_message,
    )


def cg_comparison_rows(result):
    execution, metrics, diagnostic = result.execution, result.metrics, result.diagnostics
    common = dict(
        model=execution.model_name, run_mode="cg",
        run_termination_status=execution.termination_status,
    )
    rmp = _finite(metrics.lp_value)
    certified = diagnostic.lp_convergence_proven and rmp is not None
    empty_domain = certified and diagnostic.convergence_basis == "empty_domain"
    interrupted_phase = diagnostic.interrupted_phase
    lp_interrupted = interrupted_phase not in (None, "integer_master", "layout_export")
    lp_status = diagnostic.lp_status
    pricing_status = diagnostic.pricing_status
    lp_reason = diagnostic.cg_stop_reason or diagnostic.convergence_basis
    if certified:
        lp_termination = pricing_status.termination_status or PAVER.TERMINATION_NORMAL
    elif lp_interrupted:
        lp_termination = execution.termination_status
    elif lp_reason == "wall_clock_timeout":
        lp_termination = PAVER.TERMINATION_TIME_LIMIT
    elif lp_reason == "error":
        lp_termination = PAVER.TERMINATION_ERROR
    else:
        lp_termination = next(
            (s.termination_status for s in (pricing_status, lp_status)
             if s.termination_status not in (None, PAVER.TERMINATION_NORMAL)),
            PAVER.TERMINATION_NORMAL if lp_reason else execution.termination_status,
        )
    certificate_time = diagnostic.lp_certificate_time_s
    lp = dict(
        common, value=rmp if certified else None, rmp_value=None if empty_domain else rmp,
        rmp_raw_cplex_status=lp_status.raw_cplex_status,
        value_kind=("certified_lp" if certified else "partial_rmp" if rmp is not None
                    else "unavailable"),
        lp_convergence_proven=diagnostic.lp_convergence_proven,
        convergence_basis=diagnostic.convergence_basis,
        time_s=certificate_time if certified else metrics.cg_time_s or None,
        time_basis="wall_until_certificate" if certified else "cg_phase",
        model_status=(PAVER.MODEL_STATUS_OPTIMAL if certified else
                      PAVER.MODEL_STATUS_LP_FEASIBLE if rmp is not None else lp_status.model_status),
        termination_status=lp_termination, stop_reason=lp_reason or lp_termination,
        error_message=(execution.error_message if not certified and lp_interrupted else None),
    )

    ip_status = diagnostic.integer_master_status
    ip_value = _finite(metrics.restricted_integer_master)
    ip_interrupted = interrupted_phase == "integer_master"
    ip_termination = ip_status.termination_status
    if empty_domain:
        ip_termination = PAVER.TERMINATION_NORMAL
    elif ip_interrupted:
        ip_termination = execution.termination_status
    integer = dict(
        common, value=ip_value,
        value_kind=("unavailable" if ip_value is None else
                    "optimal" if empty_domain else "restricted_integer"),
        time_s=execution.total_time_s, time_basis="end_to_end",
        integer_master_time_s=metrics.integer_master_time_s or None,
        model_status=PAVER.MODEL_STATUS_OPTIMAL if empty_domain else ip_status.model_status,
        raw_cplex_status=ip_status.raw_cplex_status, termination_status=ip_termination,
        stop_reason=("empty_domain" if empty_domain else
                     ip_termination or "integer_master_not_run"),
        error_message=execution.error_message,
    )
    return lp, integer
