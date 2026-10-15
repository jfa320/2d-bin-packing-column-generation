"""Measure additional per-iteration history cost, with aggregate timers always on.

Runs use isolated subprocesses and direct orchestrator calls, without layout
export; snapshots are discarded immediately. This does not measure all
instrumentation, IPC or CSV writing. Warmups only warm shared OS/library caches;
a failed or mismatching warmup pair skips the remaining runs of that case.
"""

import argparse
import contextlib
import csv
from datetime import datetime
import io
import json
import math
import os
from pathlib import Path
import statistics
import subprocess
import sys
import time
from unittest.mock import patch


ROOT = Path(__file__).resolve().parent
CASES = {
    "case1": (6, 4, 2, 3), "IB_001": (8, 7, 5, 2),
    "IB_002": (15, 14, 7, 3), "IB_003": (22, 15, 5, 4),
    "case18": (10, 30, 1, 6),
}
PHASES = ("master_build_time_s", "master_solve_time_s",
          "pricing_build_time_s", "pricing_solve_time_s")
METRICS = ("lp_value", "restricted_integer_master", "cg_iterations",
           "generated_columns", "cg_time_s", "master_lp_time_s",
           "pricing_time_s", "integer_master_time_s") + PHASES
FIELDS = ("case", "repeat", "warmup", "record_iterations", "worker_time_s",
          "process_time_s", "termination_status", "cg_stop_reason",
          "lp_convergence_proven", "recorded_iterations", "error") + METRICS + tuple(
              field.replace("_time_s", "_percent_cg") for field in PHASES)
PREFIX = "INSTRUMENTATION_RESULT:"


def worker(name, limit, record):
    from models.column_generation import column_generation_solver as cg
    from objects.ConfigData import ConfigData

    class SinkQueue:
        def put(self, message):
            pass

    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        with patch.object(cg, "export_final_layout", return_value=None):
            started = time.perf_counter()
            result = cg.orchestrator(
                SinkQueue(), None, limit, started, ConfigData(*CASES[name]),
                case_name=name, return_structured=True,
                finalization_heuristics=False, record_iterations=record)
            elapsed = time.perf_counter() - started
    row = {"case": name, "record_iterations": record, "worker_time_s": elapsed,
           "termination_status": result.execution.termination_status,
           "cg_stop_reason": result.diagnostics.cg_stop_reason,
           "lp_convergence_proven": result.diagnostics.lp_convergence_proven,
           "recorded_iterations": len(result.iterations),
           "error": result.execution.error_message or ""}
    row.update({field: getattr(result.metrics, field) for field in METRICS})
    for field in PHASES:
        row[field.replace("_time_s", "_percent_cg")] = (
            100 * row[field] / row["cg_time_s"] if row["cg_time_s"] else None)
    print(PREFIX + json.dumps(row, allow_nan=False))


def run_one(name, record, args):
    started = time.perf_counter()
    try:
        completed = subprocess.run(
            [sys.executable, str(Path(__file__).resolve()), "--worker", name,
             str(int(record)), "--time", str(args.time)], cwd=ROOT,
            capture_output=True, text=True, timeout=args.wall_timeout,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        if completed.returncode:
            raise RuntimeError((completed.stderr or completed.stdout)[-2000:])
        payload = next(line[len(PREFIX):] for line in reversed(completed.stdout.splitlines())
                       if line.startswith(PREFIX))
        row = json.loads(payload)
    except (subprocess.TimeoutExpired, RuntimeError, StopIteration, ValueError) as error:
        row = {"case": name, "record_iterations": record,
               "termination_status": "ExternalTimeout" if isinstance(
                   error, subprocess.TimeoutExpired) else "Error", "error": str(error)}
    row["process_time_s"] = time.perf_counter() - started
    return row


def same_trajectory(left, right):
    if any(row.get("error") or row.get("termination_status") != "Normal"
           for row in (left, right)):
        return False
    for field in ("lp_value", "restricted_integer_master"):
        if left.get(field) is None or right.get(field) is None or not math.isclose(
                left[field], right[field], rel_tol=1e-9, abs_tol=1e-8):
            return False
    return all(left.get(field) == right.get(field) for field in (
        "cg_iterations", "generated_columns", "cg_stop_reason", "lp_convergence_proven"))


def report(rows, cases, output):
    lines = ["# Additional per-iteration history cost", "",
             "Aggregate timers and snapshots remain enabled in both modes. Isolated subprocesses",
             "call the orchestrator directly; snapshots are discarded, and layout, IPC and CSV I/O are excluded.",
             "Warmups warm OS/library caches; failed/mismatching warmup pairs skip measured runs.",
             "Medians use only normal, matching trajectory pairs.",
             "Matching checks final LP/IP values, iterations, columns, stop reason and convergence.", "",
             "| Case | Valid pairs | Metric | Off median (s) | On median (s) | Delta (s) | Delta (%) | Off range (s) | On range (s) | Paired delta range (s) |",
             "|---|---:|---|---:|---:|---:|---:|---|---|---|"]
    for name in cases:
        measured = [row for row in rows if row["case"] == name and not row["warmup"]]
        pairs = []
        for repetition in sorted({row["repeat"] for row in measured}):
            modes = {row["record_iterations"]: row for row in measured if row["repeat"] == repetition}
            if len(modes) == 2 and same_trajectory(modes[False], modes[True]):
                pairs.append((modes[False], modes[True]))
        if not pairs:
            lines.append(f"| {name} | 0 | Not interpretable | NA | NA | NA | NA | NA | NA | NA |")
            continue
        for metric in ("cg_time_s", "worker_time_s"):
            off, on = ([pair[mode][metric] for pair in pairs] for mode in (0, 1))
            base, detailed = statistics.median(off), statistics.median(on)
            delta = detailed - base
            percent = f"{100 * delta / base:.2f}" if base else "NA"
            noise = [right - left for left, right in zip(off, on)]
            ranges = [f"{min(values):.6f}..{max(values):.6f}" for values in (off, on, noise)]
            lines.append(f"| {name} | {len(pairs)} | {metric} | {base:.6f} | {detailed:.6f} | {delta:.6f} | {percent} | " + " | ".join(ranges) + " |")
    lines += ["", "Small samples and short solves can be dominated by run-to-run noise; negative deltas",
              "do not establish a speedup. Failed, timed-out and mismatching pairs remain in the CSV.",
              "Four component percentages relative to CG are included in every successful CSV row."]
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", nargs="+", choices=CASES, default=list(CASES))
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--warmup", type=int, default=1)
    parser.add_argument("--time", type=float, default=15)
    parser.add_argument("--wall-timeout", type=float, default=25)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--worker", nargs=2, metavar=("CASE", "RECORD"), help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.repeats < 1 or args.warmup < 0 or not all(
            math.isfinite(value) and value > 0 for value in (args.time, args.wall_timeout)):
        parser.error("positive repeats/timeouts and nonnegative warmup are required")
    if args.worker:
        worker(args.worker[0], args.time, args.worker[1] == "1")
        return 0
    output = (args.output or ROOT / "Results" / datetime.now().strftime(
        "instrumentation_overhead_%Y%m%d_%H%M%S_%f.csv")).resolve()
    summary = output.with_suffix(".md")
    if output == summary or output.exists() or summary.exists():
        parser.error("choose a fresh .csv output and summary path")
    output.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    with output.open("x", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS)
        writer.writeheader()
        for name in args.cases:
            for index in range(args.warmup + args.repeats):
                pair = []
                for record in ((False, True) if index % 2 == 0 else (True, False)):
                    row = run_one(name, record, args)
                    row.update(repeat=index - args.warmup + 1, warmup=index < args.warmup)
                    pair.append(row)
                    rows.append(row)
                    writer.writerow(row)
                    stream.flush()
                    print(f"{name} history={record} warmup={row['warmup']} status={row.get('termination_status')}", flush=True)
                if index < args.warmup and not same_trajectory(*pair):
                    print(f"{name}: warmup not comparable; skipping remaining runs", flush=True)
                    break
    report(rows, args.cases, summary)
    print(f"CSV: {output}\nReport: {summary}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
