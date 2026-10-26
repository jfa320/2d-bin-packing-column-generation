"""Read-only analysis of independent 60s and 1200s quadrant experiments.

Creates new comparative CSVs; imports and runs no optimization model.
"""

import argparse
import csv
import json
from pathlib import Path

from utils.iteration_report import format_csv_value


EPS = 1e-9  # The unchanged experiment's EPS; used only to classify observed improvements.
SUMMARY_FIELDS = (
    "instance", "budget_s", "status", "last_rmp", "lp_certified", "lp_is_current",
    "total_time_s", "master_lp_time_s", "pricing_time_s", "pricing_percent_total",
    "pricing_solve_time_s", "q1_time_s", "q2_time_s", "q3_time_s", "q4_time_s",
    "q1_percent_pricing", "iterations", "pricing_calls", "added_columns", "duplicates",
    "final_columns", "last_improvement_iteration", "last_improvement_time_s",
    "rmp_by_60_s", "improvements_after_60_s", "stop_reason", "error_message",
    "last_rmp_attempt_value", "last_rmp_attempt_proven_optimal", "last_rmp_attempt_raw_cplex_status",
)
EVOLUTION_FIELDS = (
    "instance", "budget_s", "iteration", "rmp_completion_s", "rmp_value",
    "rmp_proven_optimal", "improved", "improvement", "time_source",
)
FINAL_PRICING_FIELDS = (
    "instance", "budget_s", "final_status", "iteration", "master_revision",
    "quadrant", "executed", "stale_after_update", "closure_proven", "raw_cplex_status",
    "termination_status", "reduced_cost", "reduced_cost_upper_bound", "best_bound",
    "pricing_objective", "sigma", "improving", "added", "wall_time_s", "error_message",
)


def numeric(value):
    return None if value in (None, "NA", "") else float(value)


def read_csv(path):
    with Path(path).open(newline="", encoding="utf-8-sig") as stream:
        return list(csv.DictReader(stream))


def experiment(path):
    path = Path(path)
    metadata = json.loads(path.with_suffix(".json").read_text(encoding="utf-8"))
    progress = {}
    directory = metadata.get("progress_directory")
    if directory:
        for source in Path(directory).glob("*.jsonl"):
            for line in source.read_text(encoding="utf-8").splitlines():
                row = json.loads(line)
                progress.setdefault(row["instance"], []).append(row)
    return {
        "rows": read_csv(path), "progress": progress,
        "iterations": read_csv(path.with_name(path.stem + "_iterations.csv")),
        "pricing": read_csv(path.with_name(path.stem + "_pricing.csv")),
    }


def evolution(instance, budget, iterations, progress=()):
    """Use observed completion times, or estimate them from remaining budgets."""
    if progress:
        points = [(r["rmp_solve"], r["elapsed_s"], r["lp_value"],
                   r.get("proven_optimal", True), "observed_completion")
                  for r in progress]
    else:
        points = [(int(r["iteration"]), budget - float(r["rmp_time_limit_s"])
                   + float(r["master_solve_time_s"]), numeric(r["lp_value"]), True,
                   "estimated_from_remaining_budget") for r in iterations]
    rows, best = [], 0.0
    for iteration, elapsed, value, proven, basis in points:
        if value is None:
            continue
        improved = proven and value > best + EPS
        delta = value - best if improved else 0.0
        rows.append(dict(instance=instance, budget_s=budget, iteration=iteration,
                         rmp_completion_s=elapsed, rmp_value=value, improved=improved,
                         rmp_proven_optimal=proven, improvement=delta, time_source=basis))
        if proven:
            best = max(best, value)
    return rows


def summarize(row, iterations, pricings, progress=()):
    name, budget = row["instance"], float(row["time_limit_s"])
    history = evolution(name, budget, iterations, progress)
    improvements = [r for r in history if r["improved"]]
    before_minute = [r for r in history if r["rmp_completion_s"] <= 60.0 and r["rmp_proven_optimal"]]
    last = improvements[-1] if improvements else {}
    quadrant_times = {k: sum(float(p["wall_time_s"]) for p in pricings if int(p["quadrant"]) == k)
                      for k in range(1, 5)}
    pricing, total = numeric(row["pricing_time_s"]), numeric(row["total_time_s"])
    summary = dict(
        instance=name, budget_s=budget, status=row["status"], last_rmp=numeric(row["lp_value"]),
        lp_certified=row["lp_convergence_proven"], lp_is_current=row["lp_is_current"],
        total_time_s=total, master_lp_time_s=numeric(row["master_lp_time_s"]),
        pricing_time_s=pricing, pricing_percent_total=100 * pricing / total if pricing and total else None,
        pricing_solve_time_s=numeric(row["pricing_solve_time_s"]),
        **{f"q{k}_time_s": v for k, v in quadrant_times.items()},
        q1_percent_pricing=100 * quadrant_times[1] / pricing if pricing else None,
        iterations=numeric(row["cg_iterations"]), pricing_calls=numeric(row["pricing_calls"]),
        added_columns=numeric(row["generated_columns"]), duplicates=numeric(row["duplicates"]),
        final_columns=numeric(row["final_columns"]),
        last_improvement_iteration=last.get("iteration"),
        last_improvement_time_s=last.get("rmp_completion_s"),
        rmp_by_60_s=before_minute[-1]["rmp_value"] if before_minute else None,
        improvements_after_60_s=sum(r["rmp_completion_s"] > 60 for r in improvements),
        stop_reason=row["cg_stop_reason"], error_message=row["error_message"],
        last_rmp_attempt_value=progress[-1]["lp_value"] if progress else None,
        last_rmp_attempt_proven_optimal=progress[-1].get("proven_optimal") if progress else None,
        last_rmp_attempt_raw_cplex_status=progress[-1].get("raw_cplex_status") if progress else None,
    )
    final = iterations[-1] if iterations else None
    tail = []
    for k in range(1, 5):
        record = next((p for p in pricings if final and p["iteration"] == final["iteration"]
                       and int(p["quadrant"]) == k), None)
        tail.append({
            "instance": name, "budget_s": budget, "final_status": row["status"],
            "iteration": final["iteration"] if final else None,
            "master_revision": final["master_revision"] if final else None,
            "quadrant": k, "executed": record is not None,
            "stale_after_update": row["lp_is_current"] == "False",
            **{key: record.get(key) if record else None for key in FINAL_PRICING_FIELDS[8:]},
        })
    return summary, history, tail


def compare(short_path, long_path, output):
    short, long = experiment(short_path), experiment(long_path)
    names = [r["instance"] for r in long["rows"]]
    if names != ["IB_010", "IIIB_009", "IIIB_006"]:
        raise ValueError("the directed experiment must contain exactly IB_010, IIIB_009, IIIB_006 in order")
    output = Path(output)
    targets = [output, output.with_name(output.stem + "_evolution.csv"),
               output.with_name(output.stem + "_final_pricing.csv")]
    inputs = {Path(short_path).resolve(), Path(long_path).resolve()}
    if output.suffix != ".csv" or any(p.resolve() in inputs or p.exists() for p in targets):
        raise FileExistsError("choose fresh .csv analysis targets distinct from the inputs")
    tables = [[], [], []]
    for name in names:
        for source in (short, long):
            row = next(r for r in source["rows"] if r["instance"] == name)
            selected_iterations = [r for r in source["iterations"] if r["instance"] == name]
            selected_pricing = [r for r in source["pricing"] if r["instance"] == name]
            summary, history, tail = summarize(row, selected_iterations, selected_pricing,
                                               source["progress"].get(name, ()))
            tables[0].append(summary)
            tables[1].extend(history)
            tables[2].extend(tail)
    for path, fields, rows in zip(targets, (SUMMARY_FIELDS, EVOLUTION_FIELDS, FINAL_PRICING_FIELDS), tables):
        with path.open("x", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            writer.writerows({key: format_csv_value(row.get(key)) for key in fields} for row in rows)
    return targets


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--short", required=True)
    parser.add_argument("--long", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    for path in compare(args.short, args.long, args.output):
        print(path)


if __name__ == "__main__":
    main()
