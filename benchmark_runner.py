"""Run canonical CG benchmarks without importing CPLEX until execution.

The 17 report fields are the eight input fields, six CG metrics, total time,
percentage gap, and status. error_message is an intentional eighteenth field:
failed runs must carry a diagnostic in their own row. A zero literature
reference is rejected because its percentage gap is undefined.
Gaps are signed: 100 * (reference - incumbent) / reference. CSV nulls are NA
and floating-point values use exactly six decimal places.

Status precedence is reference exceeded, timeout, missing LP/IP, abnormal
termination, then comparison with the literature reference. In particular a
timeout without an LP is TIMEOUT_NO_SOLUTION, not LP_FAIL. OPTIMAL means matching
the reference, not a global optimality certificate from the restricted master.
"""

import argparse
import csv
from datetime import datetime
import math
from pathlib import Path
import time

from utils.execution_result import (
    ColumnGenerationExecutionResult,
    ColumnGenerationMetrics,
    ExecutionResult,
)


DEFAULT_INPUT = "benchmark_validation_baseline(1).csv"
INPUT_FIELDS = ("instance", "family", "L", "W", "l", "w",
                "optimal_literature", "source")
OUTPUT_FIELDS = (
    "instance", "family", "L", "W", "l", "w", "optimal_literature",
    "lp_value", "restricted_integer_master", "cg_iterations", "generated_columns",
    "cg_time_s", "integer_master_time_s", "total_time_s", "gap_percent", "status",
    "source", "error_message",
)


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
    incumbent = metrics.restricted_integer_master
    reference = instance["optimal_literature"]
    gap = None if incumbent is None else 100 * (reference - incumbent) / reference
    if incumbent is not None and incumbent > reference:
        status = "REFERENCE_EXCEEDED"
    elif execution.termination_status == "TimeLimit":
        status = "TIMEOUT_NO_SOLUTION" if incumbent is None else "TIMEOUT_FEASIBLE"
    elif metrics.lp_value is None:
        status = "LP_FAIL"
    elif incumbent is None:
        status = "LP_OK_IP_FAIL"
    elif execution.termination_status != "Normal" or execution.error_message:
        status = "ERROR"
    else:
        status = "OPTIMAL" if incumbent == reference else "SUBOPTIMAL"
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
    }


def run_benchmark(input_path=DEFAULT_INPUT, output_path=None, *, max_time=1200,
                  expected_count=None, trace_path=None, execute=None):
    """Write fresh outputs and return the report Path; execute is a CG test seam.

    Relative output/trace paths are relative to the working directory. Solver
    exceptions become composed error results; output I/O errors remain fatal.
    """
    if not math.isfinite(max_time) or max_time <= 0:
        raise ValueError("max_time must be positive and finite")
    source = Path(input_path).resolve()
    output = Path(output_path or Path("Results") / datetime.now().strftime(
        "benchmark_%Y%m%d_%H%M%S_%f.csv")).resolve()
    trace = Path(trace_path).resolve() if trace_path is not None else None
    paths = [source, output] + ([trace] if trace is not None else [])
    if len(set(paths)) != len(paths):
        raise ValueError("Input, output, and trace paths must be distinct")
    for target in paths[1:]:
        if target.exists():
            raise FileExistsError(f"Output already exists: {target}")
    instances = load_instances(source, expected_count)
    if execute is None:
        from models.column_generation.column_generation_solver import execute_with_time_limit
        execute = execute_with_time_limit
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=OUTPUT_FIELDS)
        writer.writeheader()
        stream.flush()
        trace_writer = None
        if trace is not None:
            from utils.trace_file_generator import TraceFileGenerator
            trace.parent.mkdir(parents=True, exist_ok=True)
            # Reserve exclusively before handing ownership to the overwrite writer.
            with trace.open("x"):
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
                    ExecutionResult(instance["instance"], "Model5Orchestrator", 13,
                                    "Error", None, time.perf_counter() - started,
                                    error_message=f"{type(error).__name__}: {error}"),
                    ColumnGenerationMetrics(),
                )
            writer.writerow({
                field: "NA" if value is None else f"{value:.6f}" if isinstance(value, float) else value
                for field, value in result_row(instance, result).items()
            })
            stream.flush()
            if trace_writer is not None:
                trace_writer.write_trace_record(result)
    return output


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", default=DEFAULT_INPUT)
    parser.add_argument("--output")
    parser.add_argument("--trace")
    parser.add_argument("--time", type=float, default=1200, help="Seconds per instance")
    parser.add_argument("--expected-count", type=int, default=None,
                        help="Optional row-count assertion; by default all CSV rows are executed.")
    args = parser.parse_args(argv)
    try:
        output = run_benchmark(args.input, args.output, max_time=args.time,
                               expected_count=args.expected_count, trace_path=args.trace)
    except (OSError, ValueError) as error:
        parser.error(str(error))
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
