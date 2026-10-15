"""Run canonical CG benchmarks without importing CPLEX until execution.

The default report has 24 fields: the original 18 plus the essential phase
times and diagnostics. --detailed-csv exports all 44 fields, including pricing
evidence and independent solver statuses. Failed runs carry a diagnostic in
their own row. A zero literature
reference is rejected because its percentage gap is undefined.
Gaps are signed: 100 * (reference - incumbent) / reference. CSV nulls are NA
and floating-point values use exactly six decimal places.

Status precedence is reference exceeded, timeout, missing LP/IP, abnormal
termination, then comparison with the literature reference. In particular a
timeout without an LP is TIMEOUT_NO_SOLUTION, not LP_FAIL. OPTIMAL means matching
the reference, not a global optimality certificate from the restricted master.

Each run also creates <output_stem>_iterations.csv with individual attempts
and <output_stem>_phases.csv with cumulative build/solve times and percentages.
"""

import argparse
from contextlib import ExitStack
import csv
from datetime import datetime
import math
from pathlib import Path
import time

from utils.execution_result import (
    ColumnGenerationExecutionResult,
    ColumnGenerationDiagnostics,
    ColumnGenerationMetrics,
    ExecutionResult,
)
from utils.iteration_report import (
    ITERATION_OUTPUT_FIELDS, PHASE_OUTPUT_FIELDS, format_csv_value,
    iteration_rows, phase_row, report_paths,
)
from utils.paver_constants import PaverConstants
from utils.paver_runner import run_paver as execute_paver


PAVER = PaverConstants


DEFAULT_INPUT = "benchmark_validation_baseline(1).csv"
INPUT_FIELDS = ("instance", "family", "L", "W", "l", "w",
                "optimal_literature", "source")
PHASE_STATUS_PREFIXES = (
    "lp", "pricing", "pricing_phase2", "auxiliary_pricing",
    "auxiliary_pricing_phase2", "integer_master",
)
DIAGNOSTIC_FIELDS = (
    "master_lp_time_s", "pricing_time_s", "cg_stop_reason",
    "lp_convergence_proven", "convergence_basis", "interrupted_phase",
    "pricing_objective", "pricing_best_bound",
) + tuple(
    f"{phase}_{field}" for phase in PHASE_STATUS_PREFIXES
    for field in ("model_status", "termination_status", "raw_cplex_status")
)
BASE_OUTPUT_FIELDS = (
    "instance", "family", "L", "W", "l", "w", "optimal_literature",
    "lp_value", "restricted_integer_master", "cg_iterations", "generated_columns",
    "cg_time_s", "integer_master_time_s", "total_time_s", "gap_percent", "status",
    "source", "error_message",
)
OUTPUT_FIELDS = BASE_OUTPUT_FIELDS + (
    "master_lp_time_s", "pricing_time_s", "cg_stop_reason",
    "lp_convergence_proven", "interrupted_phase", "integer_master_model_status",
)
DETAILED_OUTPUT_FIELDS = BASE_OUTPUT_FIELDS + DIAGNOSTIC_FIELDS


def load_instances(filename, expected_count=None):
    """Validate every CSV row and retain its order.

    ``expected_count`` is an optional assertion for controlled experiments;
    the normal benchmark size is determined by the input file itself.
    """
    if expected_count is not None and (
            isinstance(expected_count, bool) or not isinstance(expected_count, int)
            or expected_count <= 0):
        raise ValueError("expected_count must be a positive integer")
    rows = []
    seen = set()
    with Path(filename).open(newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        fields = reader.fieldnames or []
        if len(fields) != len(set(fields)) or not set(INPUT_FIELDS).issubset(fields):
            raise ValueError("CSV requires unique headers including: " + ",".join(INPUT_FIELDS))
        for line, raw in enumerate(reader, 2):
            if None in raw or any(raw.get(field) is None for field in fields):
                raise ValueError(f"Row {line}: malformed CSV row")
            row = {field: raw[field].strip() for field in INPUT_FIELDS}
            for field in ("instance", "family", "source"):
                if not row[field]:
                    raise ValueError(f"Row {line}: {field} must be nonempty")
            if row["instance"] in seen:
                raise ValueError(f"Row {line}: duplicate instance {row['instance']!r}")
            seen.add(row["instance"])
            for field in ("L", "W", "l", "w"):
                try:
                    value = int(row[field])
                except ValueError:
                    raise ValueError(f"Row {line}: {field} must be a positive integer") from None
                if value <= 0:
                    raise ValueError(f"Row {line}: {field} must be a positive integer")
                row[field] = value
            try:
                reference = float(row["optimal_literature"])
            except ValueError:
                reference = float("nan")
            if not math.isfinite(reference) or reference <= 0:
                raise ValueError(f"Row {line}: optimal_literature must be positive and finite; zero gap denominator is undefined")
            row["optimal_literature"] = reference
            rows.append(row)
    if expected_count is not None and len(rows) != expected_count:
        raise ValueError(f"Expected {expected_count} instances, found {len(rows)}")
    return rows


def result_row(instance, result):
    """Convert the composed CG return contract into one CSV record."""
    execution, metrics = result.execution, result.metrics
    diagnostics = result.diagnostics
    incumbent = metrics.restricted_integer_master
    reference = instance["optimal_literature"]
    gap = None if incumbent is None else 100 * (reference - incumbent) / reference
    if incumbent is not None and incumbent > reference:
        status = "REFERENCE_EXCEEDED"
    elif execution.termination_status == PAVER.TERMINATION_TIME_LIMIT:
        status = "TIMEOUT_NO_SOLUTION" if incumbent is None else "TIMEOUT_FEASIBLE"
    elif metrics.lp_value is None:
        status = "LP_FAIL"
    elif incumbent is None:
        status = "LP_OK_IP_FAIL"
    elif execution.termination_status != PAVER.TERMINATION_NORMAL or execution.error_message:
        status = "ERROR"
    else:
        status = "OPTIMAL" if incumbent == reference else "SUBOPTIMAL"
    phase_statuses = {
        f"{phase}_{field}": getattr(getattr(diagnostics, phase + "_status"), field)
        for phase in PHASE_STATUS_PREFIXES
        for field in ("model_status", "termination_status", "raw_cplex_status")
    }
    return {
        **instance,
        "lp_value": metrics.lp_value,
        "restricted_integer_master": incumbent,
        "cg_iterations": metrics.cg_iterations,
        "generated_columns": metrics.generated_columns,
        "cg_time_s": metrics.cg_time_s,
        "integer_master_time_s": metrics.integer_master_time_s,
        "total_time_s": execution.total_time_s,
        "gap_percent": gap,
        "status": status,
        "error_message": execution.error_message,
        "master_lp_time_s": metrics.master_lp_time_s,
        "pricing_time_s": metrics.pricing_time_s,
        **{field: getattr(diagnostics, field) for field in (
            "cg_stop_reason", "lp_convergence_proven", "convergence_basis",
            "interrupted_phase", "pricing_objective", "pricing_best_bound",
        )},
        **phase_statuses,
    }


def _resolve_output_paths(output_path, trace_path, run_paver_after):
    output = Path(output_path or Path("Results") / datetime.now().strftime(
        "benchmark_%Y%m%d_%H%M%S_%f.csv")).resolve()
    if run_paver_after and trace_path is None:
        trace_path = output.with_suffix(".trc")
    trace = Path(trace_path).resolve() if trace_path is not None else None
    return output, trace


def _validate_distinct_paths(source, output, trace):
    paths = [source, *_output_targets(output, trace)]
    if len(set(paths)) != len(paths):
        raise ValueError("Input, output, iteration, phase, and trace paths must be distinct")


def _output_targets(output, trace):
    return [output, *report_paths(output)] + ([trace] if trace is not None else [])


def _confirm_overwrite(paths):
    print("Ya existen estos archivos:")
    for path in paths:
        print(f"  {path}")
    try:
        response = input("¿Querés sobrescribirlos? [s/N]: ").strip().casefold()
    except EOFError:
        return False
    return response in {"s", "si", "sí", "y", "yes"}


def run_benchmark(input_path=DEFAULT_INPUT, output_path=None, *, max_time=1200,
                  expected_count=None, trace_path=None, execute=None,
                  run_paver_after=False, paver_path=None, paver_output=None,
                  overwrite=False, detailed_csv=False):
    """Write outputs and return the report Path; execute is a CG test seam.

    Relative output/trace paths are relative to the working directory. Solver
    exceptions become composed error results; output I/O errors remain fatal.
    Existing files are replaced only when overwrite is explicitly enabled.
    detailed_csv includes all per-phase statuses and convergence evidence.
    Iteration history and cumulative phase percentages are always exported in
    separate CSVs beside the principal report, with one flush per instance.
    """
    if not math.isfinite(max_time) or max_time <= 0:
        raise ValueError("max_time must be positive and finite")
    source = Path(input_path).resolve()
    output, trace = _resolve_output_paths(output_path, trace_path, run_paver_after)
    _validate_distinct_paths(source, output, trace)
    targets = _output_targets(output, trace)
    for target in targets:
        if target.exists():
            if not overwrite:
                raise FileExistsError(f"Output already exists: {target}")
    instances = load_instances(source, expected_count)
    if execute is None:
        from models.column_generation.column_generation_solver import execute_with_time_limit
        execute = execute_with_time_limit
    output.parent.mkdir(parents=True, exist_ok=True)
    output_mode = "w" if overwrite else "x"
    report_fields = DETAILED_OUTPUT_FIELDS if detailed_csv else OUTPUT_FIELDS
    iteration_path, phase_path = report_paths(output)
    with ExitStack() as stack:
        stream = stack.enter_context(output.open(output_mode, newline="", encoding="utf-8"))
        iteration_stream = stack.enter_context(iteration_path.open(output_mode, newline="", encoding="utf-8"))
        phase_stream = stack.enter_context(phase_path.open(output_mode, newline="", encoding="utf-8"))
        writer = csv.DictWriter(stream, fieldnames=report_fields)
        iteration_writer = csv.DictWriter(iteration_stream, fieldnames=ITERATION_OUTPUT_FIELDS)
        phase_writer = csv.DictWriter(phase_stream, fieldnames=PHASE_OUTPUT_FIELDS)
        writer.writeheader()
        iteration_writer.writeheader()
        phase_writer.writeheader()
        stream.flush()
        iteration_stream.flush()
        phase_stream.flush()
        trace_writer = None
        if trace is not None:
            from utils.trace_file_generator import TraceFileGenerator
            trace.parent.mkdir(parents=True, exist_ok=True)
            # Ensure the target exists before the trace writer takes ownership.
            trace_mode = "w" if overwrite else "x"
            with trace.open(trace_mode):
                pass
            trace_writer = TraceFileGenerator(str(trace), mode="overwrite", directory="Results")
        for instance in instances:
            solver_instance = {
                "case_name": instance["instance"],
                "bin_width": instance["L"], "bin_height": instance["W"],
                "item_width": instance["l"], "item_height": instance["w"],
            }
            started = time.perf_counter()
            try:
                result = execute(max_time, instance=solver_instance, finalization_heuristics=False)
                if not isinstance(result, ColumnGenerationExecutionResult):
                    raise TypeError("CG must return ColumnGenerationExecutionResult")
            except Exception as error:
                result = ColumnGenerationExecutionResult(
                    ExecutionResult(instance["instance"], "Model5Orchestrator",
                                    PAVER.MODEL_STATUS_ERROR,
                                    PAVER.TERMINATION_ERROR, None,
                                    time.perf_counter() - started,
                                    error_message=f"{type(error).__name__}: {error}"),
                    ColumnGenerationMetrics(),
                    ColumnGenerationDiagnostics(cg_stop_reason="error", interrupted_phase="runner"),
                )
            writer.writerow({
                field: format_csv_value(value)
                for field, value in result_row(instance, result).items()
                if field in report_fields
            })
            iteration_writer.writerows(
                {field: format_csv_value(value) for field, value in row.items()}
                for row in iteration_rows(instance, result)
            )
            phase_writer.writerow({
                field: format_csv_value(value)
                for field, value in phase_row(instance, result).items()
            })
            stream.flush()
            iteration_stream.flush()
            phase_stream.flush()
            if trace_writer is not None:
                trace_writer.write_trace_record(result)
    if run_paver_after:
        paver_result = execute_paver(
            trace,
            paver_path,
            paver_output,
            failtime=max_time,
        )
        if paver_result.success:
            print(paver_result.message)
        else:
            # PAVER is post-processing; keep the CSV and trace even if it is unavailable.
            print(f"ERROR: {paver_result.message}")
    return output


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", default=DEFAULT_INPUT)
    parser.add_argument("--output")
    parser.add_argument("--trace")
    parser.add_argument("--time", type=float, default=1200, help="Seconds per instance")
    parser.add_argument("--detailed-csv", action="store_true",
                        help="Export all 44 diagnostic fields instead of the default 24.")
    parser.add_argument("--expected-count", type=int, default=None,
                        help="Optional row-count assertion; by default all CSV rows are executed.")
    paver_group = parser.add_mutually_exclusive_group()
    paver_group.add_argument("--paver", dest="run_paver", action="store_true",
                             help="Run PAVER after the CSV/trace are generated (default).")
    paver_group.add_argument("--no-paver", dest="run_paver", action="store_false",
                             help="Only generate the CSV and optional trace.")
    parser.set_defaults(run_paver=True)
    parser.add_argument("--paver-path", default=None,
                        help="Override the PAVER root configured in paver.properties.")
    parser.add_argument("--paver-output", default=None,
                        help="Directory for the PAVER HTML report.")
    args = parser.parse_args(argv)
    source = Path(args.input).resolve()
    output_path, trace_path = _resolve_output_paths(
        args.output, args.trace, args.run_paver,
    )
    try:
        _validate_distinct_paths(source, output_path, trace_path)
    except ValueError as error:
        parser.error(str(error))

    output_targets = _output_targets(output_path, trace_path)
    existing_outputs = [path for path in output_targets if path.exists()]
    overwrite = False
    if existing_outputs:
        if not _confirm_overwrite(existing_outputs):
            print("Cancelado. No se modificó ningún archivo.")
            return 1
        overwrite = True

    try:
        output = run_benchmark(args.input, output_path, max_time=args.time,
                               expected_count=args.expected_count, trace_path=trace_path,
                               run_paver_after=args.run_paver,
                               paver_path=args.paver_path,
                               paver_output=args.paver_output,
                               overwrite=overwrite, detailed_csv=args.detailed_csv)
    except (OSError, ValueError) as error:
        parser.error(str(error))
    print(output)
    for path in report_paths(output):
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
