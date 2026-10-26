"""Independent Checkpoint E experiment; never registered in the main benchmark.

Run from the repository root. The default is one sequential pass over the
applicable baseline rows, with alpha=0.8 and a 60-second global algorithm
budget per row. Every input row is reported, including NOT_APPLICABLE rows.
"""

import argparse
from contextlib import contextmanager
import csv
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import subprocess
import sys
import time
from unittest.mock import patch

from benchmark_runner import load_instances
from models.quadrant_column_generation.quadrants import build_quadrants
from utils.iteration_report import format_csv_value


ROOT = Path(__file__).resolve().parent
PREFIX = "QUADRANT_PILOT_RESULT:"
FIELDS = (
    "instance", "family", "L", "W", "l", "w", "alpha", "applicable",
    "lp_value", "status", "total_time_s", "algorithm_time_s", "geometry_time_s",
    "root_time_s", "master_lp_time_s", "master_build_time_s",
    "master_solve_time_s", "master_update_time_s", "master_close_time_s",
    "pricing_time_s", "pricing_solve_time_s", "cg_iterations", "pricing_calls",
    "initial_columns", "generated_columns", "duplicates", "final_columns",
    "optimal_literature", "lp_gap_percent", "lp_excess_percent", "area_upper_bound",
    "lp_convergence_proven", "lp_is_current", "had_timeouts", "cg_stop_reason",
    "time_limit_s", "global_points", "global_placements", "source", "error_message",
)
ITERATION_FIELDS = (
    "instance", "iteration", "master_revision", "lp_value", "sigma",
    "nonzero_pi_count", "pool_before", "pool_after", "columns_found",
    "generated_columns", "duplicates", "pricing_calls", "rmp_time_limit_s",
    "master_solve_time_s", "pricing_time_s", "column_update_time_s",
    "iteration_time_s", "outcome", "stop_reason",
)
PRICING_FIELDS = (
    "instance", "iteration", "master_revision", "quadrant", "time_limit_s",
    "sigma", "pricing_objective", "reduced_cost", "reduced_cost_upper_bound",
    "best_bound", "proven_optimal", "closure_proven", "closure_basis",
    "model_status", "termination_status", "raw_cplex_status", "selected_items",
    "improving", "added", "duplicate", "wall_time_s", "solve_time_s", "error_message",
)


@contextmanager
def measure_master(module, totals, on_master_solve=None):
    """Time existing master operations without changing their arguments/results.

    Initial build includes adding the four seeds. Incremental updates, solve
    (including result/dual extraction) and disposal are disjoint measurements.
    This instrumentation is installed only inside an isolated pilot worker.
    """
    original = module.RestrictedMasterBuilder

    def timed(phase, operation, *args, **kwargs):
        started = time.perf_counter()
        try:
            return operation(*args, **kwargs)
        finally:
            totals[phase] += time.perf_counter() - started

    class Master:
        def __init__(self, inner):
            self.inner = inner

        def __getattr__(self, name):
            return getattr(self.inner, name)

        def solve(self):
            result = timed("solve", self.inner.solve)
            if on_master_solve is not None:
                on_master_solve(self.inner, result)
            return result

        def add_configuration(self, configuration):
            return timed("update", self.inner.add_configuration, configuration)

        def close(self):
            return timed("close", self.inner.close)

    class Builder:
        def __init__(self, *args, **kwargs):
            self.inner = original(*args, **kwargs)
            self.quadrants = self.inner.quadrants

        def build(self, *args, **kwargs):
            return Master(timed("build", self.inner.build, *args, **kwargs))

    with patch.object(module, "RestrictedMasterBuilder", Builder):
        yield


@contextmanager
def progress_sink(instance, started, totals):
    """Optional observational RMP snapshots for long, sequential experiments.

    No model/price/result is mutated. Enabled only by the explicitly supplied
    QUADRANT_PILOT_PROGRESS_DIR environment variable. I/O consumes algorithm
    budget, outside the measured native master operations. Normal runs retain
    their original output contract and produce no extra file.
    """
    directory = os.environ.get("QUADRANT_PILOT_PROGRESS_DIR")
    if not directory:
        yield None
        return
    path = Path(directory)
    path.mkdir(parents=True, exist_ok=True)
    # An ordinal-free file name still cannot escape the selected directory.
    filename = hashlib.sha256(instance["instance"].encode("utf-8")).hexdigest()[:16] + ".jsonl"
    with (path / filename).open("x", encoding="utf-8") as stream:
        count = 0

        def observe(master, result):
            nonlocal count
            count += 1
            duals = result.duals
            snapshot = {
                "instance": instance["instance"], "rmp_solve": count,
                "elapsed_s": time.perf_counter() - started,
                "model_revision": result.model_revision,
                "lp_value": result.objective_value, "proven_optimal": result.proven_optimal,
                "raw_cplex_status": result.raw_cplex_status,
                "pool_size": len(master.configurations),
                "sigma": dict(duals.sigma) if duals else None,
                "master_lp_time_s": sum(totals.values()),
            }
            stream.write(json.dumps(snapshot, allow_nan=False) + "\n")
            stream.flush()

        yield observe


def base_row(instance, limit):
    dimensions = tuple(instance[key] for key in ("L", "W", "l", "w"))
    applicability = build_quadrants(*dimensions, alpha=0.8)
    return {
        **instance, "alpha": 0.8, "applicable": applicability.applicable,
        "time_limit_s": limit,
        "area_upper_bound": dimensions[0] * dimensions[1] // (dimensions[2] * dimensions[3]),
    }, applicability


def classify(result):
    """Convergence is a proof; historical timeout flags remain separate."""
    if result.converged and result.lp_is_current:
        return "CONVERGED"
    if result.stop_reason == "global_deadline":
        return "TIMEOUT"
    errors = [result.error_message]
    errors += [i.rmp.error_message for i in result.iterations if i.rmp is not None]
    errors += [p.error_message or (p.result.error_message if p.result else None)
               for i in result.iterations for p in i.pricings]
    if any(errors):
        return "ERROR"
    if result.had_timeouts or result.stop_reason == "global_deadline":
        return "TIMEOUT"
    return "INCONCLUSIVE"


def project(instance, limit, result, totals):
    """Export the last RMP value, but compute LP gaps only after certified closure."""
    row, _ = base_row(instance, limit)
    iterations, pricings = [], []
    for iteration in result.iterations:
        iterations.append({
            "instance": instance["instance"], "iteration": iteration.iteration,
            "master_revision": iteration.master_revision,
            "lp_value": iteration.rmp.objective_value if iteration.rmp else None,
            "sigma": json.dumps(iteration.sigma, sort_keys=True),
            "nonzero_pi_count": iteration.nonzero_pi_count,
            "pool_before": iteration.pool_before, "pool_after": iteration.pool_after,
            "columns_found": len(iteration.columns_found),
            "generated_columns": len(iteration.columns_added),
            "duplicates": len(iteration.duplicates), "pricing_calls": len(iteration.pricings),
            "rmp_time_limit_s": iteration.rmp_time_limit_s,
            "master_solve_time_s": iteration.rmp_wall_time_s,
            "pricing_time_s": iteration.pricing_wall_time_s,
            "column_update_time_s": iteration.column_update_time_s,
            "iteration_time_s": iteration.iteration_time_s,
            "outcome": iteration.outcome, "stop_reason": iteration.stop_reason,
        })
        for record in iteration.pricings:
            pricing = record.result
            pricings.append({
                "instance": instance["instance"], "iteration": iteration.iteration,
                "master_revision": record.master_revision, "quadrant": record.quadrant,
                "time_limit_s": record.time_limit_s,
                "sigma": pricing.sigma if pricing else iteration.sigma.get(record.quadrant),
                **{key: getattr(pricing, key) if pricing else None for key in (
                    "pricing_objective", "reduced_cost", "reduced_cost_upper_bound",
                    "best_bound", "proven_optimal", "closure_proven", "closure_basis",
                    "raw_cplex_status", "solve_time_s",
                )},
                "model_status": pricing.status.model_status if pricing else None,
                "termination_status": pricing.status.termination_status if pricing else None,
                "selected_items": (pricing.configuration.item_count
                                   if pricing and pricing.configuration is not None else None),
                "improving": record.improving, "added": record.added,
                "duplicate": record.duplicate, "wall_time_s": record.wall_time_s,
                "error_message": record.error_message or (pricing.error_message if pricing else None),
            })
    proof = result.converged and result.lp_is_current
    reference = instance["optimal_literature"]
    gap = (100 * (reference - result.objective_value) / reference
           if proof and result.objective_value is not None else None)
    errors = [result.error_message]
    errors += [i.rmp.error_message for i in result.iterations if i.rmp]
    errors += [p["error_message"] for p in pricings]
    row.update(
        lp_value=result.objective_value, status=classify(result), root_time_s=result.total_time_s,
        master_lp_time_s=sum(totals.values()),
        **{f"master_{key}_time_s": value for key, value in totals.items()},
        pricing_time_s=sum(i.pricing_wall_time_s for i in result.iterations),
        pricing_solve_time_s=sum(p["solve_time_s"] or 0.0 for p in pricings),
        cg_iterations=len(iterations), pricing_calls=len(pricings), initial_columns=4,
        generated_columns=sum(len(i.columns_added) for i in result.iterations),
        duplicates=sum(len(i.duplicates) for i in result.iterations),
        final_columns=len(result.configurations), lp_gap_percent=gap,
        lp_excess_percent=-gap if gap is not None else None,
        lp_convergence_proven=proof, lp_is_current=result.lp_is_current,
        had_timeouts=result.had_timeouts, cg_stop_reason=result.stop_reason,
        error_message=" | ".join(dict.fromkeys(e for e in errors if e)) or None,
    )
    return {"row": row, "iterations": iterations, "pricings": pricings}


def worker(instance, limit):
    # Imports and process creation are in total_time_s, outside the algorithm
    # deadline. The deadline itself includes global discretization and root CG.
    from models.quadrant_column_generation.discretization import generate_global_discretization
    from models.quadrant_column_generation import root_solver

    started = time.perf_counter()
    row, quadrants = base_row(instance, limit)
    grid = generate_global_discretization(*(instance[k] for k in ("L", "W", "l", "w")))
    geometry_time = time.perf_counter() - started
    totals = dict.fromkeys(("build", "solve", "update", "close"), 0.0)
    with progress_sink(instance, started, totals) as observe:
        with measure_master(root_solver, totals, observe):
            result = root_solver.solve_root(
                grid, quadrants.quadrants,
                time_limit_s=max(0.0, limit - (time.perf_counter() - started)),
            )
    elapsed = time.perf_counter() - started
    payload = project(instance, limit, result, totals)
    payload["row"].update(
        algorithm_time_s=elapsed, geometry_time_s=geometry_time,
        global_points=len(grid.I) * len(grid.J), global_placements=len(grid.placements),
    )
    print(PREFIX + json.dumps(payload, allow_nan=False), flush=True)


def run_one(instance, limit, grace=15.0):
    row, applicability = base_row(instance, limit)
    if not applicability.applicable:
        row.update(status="NOT_APPLICABLE", total_time_s=0.0,
                   cg_stop_reason=applicability.reason, lp_convergence_proven=False)
        return {"row": row, "iterations": [], "pricings": []}
    started = time.perf_counter()
    try:
        completed = subprocess.run(
            [sys.executable, str(Path(__file__).resolve()), "--worker", json.dumps(instance),
             "--time", str(limit)], cwd=ROOT, capture_output=True, text=True,
            timeout=limit + grace,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        if completed.returncode:
            raise RuntimeError((completed.stderr or completed.stdout)[-3000:])
        payload = next(line[len(PREFIX):] for line in reversed(completed.stdout.splitlines())
                       if line.startswith(PREFIX))
        result = json.loads(payload)
    except (subprocess.TimeoutExpired, RuntimeError, StopIteration, ValueError) as error:
        timeout = isinstance(error, subprocess.TimeoutExpired)
        row.update(status="TIMEOUT" if timeout else "ERROR", had_timeouts=timeout,
                   lp_convergence_proven=False, cg_stop_reason="external_timeout" if timeout else "worker_error",
                   error_message=str(error))
        # With no completed worker result, phase metrics are unknown, not zero.
        result = {"row": row, "iterations": [], "pricings": []}
    result["row"]["total_time_s"] = time.perf_counter() - started
    return result


def metadata(source, limit, grace):
    import cplex

    def git(*args):
        return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()

    with cplex.Cplex() as model:
        parameters = {name: getattr(model.parameters, name).get() for name in (
            "threads", "clocktype", "randomseed",
        )}
        parameters["mip.tolerances.mipgap"] = model.parameters.mip.tolerances.mipgap.get()
    return {
        "started_utc": datetime.now(timezone.utc).isoformat(),
        "input": str(source), "input_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "git_commit": git("rev-parse", "HEAD"), "git_status": git("status", "--short"),
        "python": sys.version, "executable": sys.executable, "platform": platform.platform(),
        "processor": platform.processor(), "logical_cpus": os.cpu_count(), "cplex": cplex.__version__,
        "cplex_defaults": parameters, "alpha": 0.8, "time_limit_s": limit,
        "external_timeout_s": limit + grace, "repetitions": 1, "warmups": 0,
        "progress_directory": os.environ.get("QUADRANT_PILOT_PROGRESS_DIR"),
        "quadrant_order": [1, 2, 3, 4], "initial_columns": "one empty configuration per quadrant",
        "comparison": "No historical slice-CG run has verified matching budget and protocol; no timing comparison.",
        "timing": "perf_counter wall time; total includes process startup/imports/serialization/exit. Algorithm deadline includes geometry and root CG. RMP includes build/seeds, solve/duals, updates, disposal; pricing includes construction/solve/postprocessing.",
    }


def run_pilot(source, output, *, limit=60.0, grace=15.0):
    if not all(math.isfinite(x) and x > 0 for x in (limit, grace)):
        raise ValueError("time and external grace must be positive and finite")
    source, output = Path(source).resolve(), Path(output).resolve()
    targets = [output, output.with_name(output.stem + "_iterations.csv"),
               output.with_name(output.stem + "_pricing.csv"), output.with_suffix(".json")]
    if output.suffix != ".csv" or source in targets or len(set(targets)) != 4:
        raise ValueError("choose distinct input and .csv output paths")
    if any(path.exists() for path in targets):
        raise FileExistsError("choose fresh pilot output paths")
    instances = load_instances(source)
    info = metadata(source, limit, grace)
    output.parent.mkdir(parents=True, exist_ok=True)
    targets[3].write_text(json.dumps(info, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    with output.open("x", newline="", encoding="utf-8") as stream, \
            targets[1].open("x", newline="", encoding="utf-8") as iteration_stream, \
            targets[2].open("x", newline="", encoding="utf-8") as pricing_stream:
        writers = [csv.DictWriter(s, fieldnames=fields) for s, fields in zip(
            (stream, iteration_stream, pricing_stream), (FIELDS, ITERATION_FIELDS, PRICING_FIELDS))]
        for writer in writers:
            writer.writeheader()
        for instance in instances:
            payload = run_one(instance, limit, grace)
            for writer, fields, records in zip(writers, (FIELDS, ITERATION_FIELDS, PRICING_FIELDS),
                                               ([payload["row"]], payload["iterations"], payload["pricings"])):
                writer.writerows({key: format_csv_value(record.get(key)) for key in fields}
                                 for record in records)
            for handle in (stream, iteration_stream, pricing_stream):
                handle.flush()
            row = payload["row"]
            print(f"{row['instance']}: {row['status']} LP={row.get('lp_value')} "
                  f"iterations={row.get('cg_iterations')} time={row['total_time_s']:.3f}s", flush=True)
    return output


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", default="benchmark_validation_baseline.csv")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--time", type=float, default=60.0)
    parser.add_argument("--external-grace", type=float, default=15.0)
    parser.add_argument("--worker", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.worker:
        worker(json.loads(args.worker), args.time)
        return 0
    output = args.output or Path("Results") / datetime.now().strftime("quadrant_pilot_%Y%m%d_%H%M%S_%f.csv")
    print(run_pilot(args.input, output, limit=args.time, grace=args.external_grace))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
