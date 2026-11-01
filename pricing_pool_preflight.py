"""Phase-zero diagnostic: observe a one-column trajectory, then replay duals.

No extra candidate is ever added to the master. Baseline observation and offline
replays have separate budgets; these runs are not a multiple-column benchmark.
Run from the repository root. Outputs are fresh, persistent and solver-versioned.
"""

import argparse
import contextlib
import csv
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import io
import json
import math
import os
from pathlib import Path
import platform
import statistics
import subprocess
import sys
import time
from unittest.mock import patch


ROOT = Path(__file__).resolve().parent


def catalog():
    from config import get_instance
    from instances import DEFAULT_INSTANCES
    cases = {name: get_instance(name) for name in DEFAULT_INSTANCES}
    with (ROOT / "benchmark_validation_baseline.csv").open(encoding="utf-8-sig") as stream:
        for row in csv.DictReader(stream):
            cases[row["instance"]] = dict(
                case_name=row["instance"], bin_width=int(row["L"]),
                bin_height=int(row["W"]), item_width=int(row["l"]), item_height=int(row["w"]))
    return cases


def persist(path, payload):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, indent=2, allow_nan=False), encoding="utf-8")
    # Windows indexers/antivirus can briefly hold an existing JSON open without
    # delete sharing. Retain the complete temporary file and retry the rename.
    for delay in (0.01, 0.02, 0.05, 0.1, 0.25, None):
        try:
            temporary.replace(path)
            return
        except PermissionError:
            if delay is None:
                raise
            time.sleep(delay)


def worker(args):
    import cplex
    from models.column_generation import column_generation_solver as cg
    from models.column_generation import slave_problem as slave
    from models.column_generation.orchestrator_services import ProblemNormalizer
    from models.column_generation.solution_pool import (
        PricingGeometry, candidate_from_values, read_solution_pool, slice_master_key,
    )
    from models.common.position_generator import generate_positions_xym
    from objects.ConfigData import ConfigData
    from utils.execution_result import ColumnGenerationExecutionResult

    instance = catalog()[args.case]
    config = ConfigData(*(instance[key] for key in (
        "bin_width", "bin_height", "item_width", "item_height")))
    normalized = ProblemNormalizer().normalize(config)
    geometry = PricingGeometry(normalized.bin_width, normalized.bin_height,
                               normalized.item_width, normalized.item_height,
                               normalized.slice_height)
    report = dict(case=args.case, seed=args.seed, mode=args.mode, baseline=None,
                  observations=[], replays=[], snapshots=[], complete=False,
                  budget_exhausted=False, error=None)
    started = time.perf_counter()
    deadline = started + args.time
    slices, snapshots, duals = [], [], None
    last_persist = started

    class Sink:
        def put(self, message):
            if isinstance(message, ColumnGenerationExecutionResult):
                report["last_progress"] = dict(metrics=asdict(message.metrics),
                                               diagnostics=asdict(message.diagnostics))

    def configure(model, intensity=1):
        for setter in (model.set_log_stream, model.set_results_stream,
                       model.set_warning_stream, model.set_error_stream):
            setter(None)
        model.parameters.threads.set(1)
        model.parameters.randomseed.set(args.seed)
        model.parameters.mip.pool.intensity.set(intensity)
        model.parameters.mip.pool.capacity.set(args.capacity)
        return model

    def limit(model):
        remaining = deadline - time.perf_counter()
        if remaining <= 0:
            report["budget_exhausted"] = True
            raise TimeoutError("Preflight baseline global budget exhausted")
        model.parameters.timelimit.set(remaining)

    original_master_builder = cg.create_master_model
    original_pricing_builder = slave.create_slave_model
    original_master_solver = cg.solve_master_model
    original_slave_solver = cg.solve_slave_model

    def build_master(*values):
        nonlocal slices
        slices = values[1]
        return configure(original_master_builder(*values))

    def build_pricing(*values):
        return configure(original_pricing_builder(*values))

    def solve_master(model, queue, manual, relaxed, initial):
        nonlocal duals
        limit(model)
        response = original_master_solver(model, queue, manual, relaxed, initial)
        if relaxed:
            duals = response[1]
        return response

    def solve_pricing(model, *values, **kwargs):
        nonlocal last_persist
        limit(model)
        before = time.perf_counter()
        response = original_slave_solver(model, *values, **kwargs)
        primary_time = time.perf_counter() - before
        primary_key = slice_master_key(response[0]) if response[0] is not None else None
        row = dict(iteration=len(report["observations"]) + 1,
                   primary_time_s=primary_time, primary_value=response[1],
                   primary_key_hash=hashlib.sha256(repr(primary_key).encode()).hexdigest())
        if args.mode == "observe":
            extraction_started = time.perf_counter()
            known = {slice_master_key(slice_) for slice_ in slices}
            incumbent = candidate_from_values(
                model.variables.get_names(), model.solution.get_values(), duals, geometry,
                coefficients=model.objective.get_linear(), reported_objective=response[1]
            ) if model.solution.is_primal_feasible() else None
            read = read_solution_pool(model, duals, geometry, known, incumbent,
                                      max_extra=args.batch_size - 1)
            row.update(asdict(read))
            row.pop("candidates")
            row["extraction_time_s"] = time.perf_counter() - extraction_started
            # Immutable snapshots: the reusable pricing will change its objective.
            snapshots.append(dict(duals={"pi": dict(duals["pi"])}, known_keys=known,
                                  iteration=row["iteration"], objective=response[1]))
        report["observations"].append(row)
        now = time.perf_counter()
        if now - last_persist >= 0.25 or len(report["observations"]) == 1 or response[1] is None or response[1] <= 1e-9:
            persist(args.result, report)
            last_persist = now
        return response

    try:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            with (patch.object(cg, "export_final_layout", return_value=None),
                  patch.object(cg, "create_master_model", side_effect=build_master),
                  patch.object(slave, "create_slave_model", side_effect=build_pricing),
                  patch.object(cg, "solve_master_model", side_effect=solve_master),
                  patch.object(cg, "solve_slave_model", side_effect=solve_pricing)):
                result = cg.orchestrator(
                    Sink(), None, args.time, started, config, case_name=args.case,
                    return_structured=True, finalization_heuristics=False,
                    pricing_mode="reuse", use_pricing_pool=False)
        report["baseline"] = dict(metrics=asdict(result.metrics),
                                  diagnostics=asdict(result.diagnostics),
                                  execution=asdict(result.execution))
        report["baseline_wall_s"] = time.perf_counter() - started
        if result.execution.error_message:
            report["error"] = result.execution.error_message
        persist(args.result, report)
        if args.mode == "observe" and snapshots and (
                not report["error"] or report["budget_exhausted"]):
            positive = [i for i, snapshot in enumerate(snapshots)
                        if snapshot["objective"] is not None and snapshot["objective"] > 1e-9]
            chosen = sorted({positive[0], positive[len(positive) // 2], positive[-1],
                             len(snapshots) - 1}) if positive else [len(snapshots) - 1]
            xy_x, xy_y = generate_positions_xym(
                geometry.bin_width, geometry.bin_height, geometry.item_width, geometry.item_height)
            replay_deadline = time.perf_counter() + args.replay_time
            for strategy, intensity in (("passive", 1), ("populate", 2)):
                session = slave.IncrementalPricingModel(
                    args.replay_time, xy_x, xy_y, geometry.bin_width,
                    geometry.item_height, geometry.item_width, geometry.bin_height,
                    geometry.slice_height)
                try:
                    for index in chosen:
                        remaining = replay_deadline - time.perf_counter()
                        if remaining <= 0:
                            report["replay_budget_exhausted"] = True
                            break
                        snapshot = snapshots[index]
                        model = configure(session.prepare(snapshot["duals"]), intensity)
                        model.parameters.timelimit.set(remaining)
                        begin = time.perf_counter()
                        model.solve()
                        solve_s = time.perf_counter() - begin
                        primary = dict(status=model.solution.get_status(), objective=None, bound=None)
                        incumbent = None
                        if model.solution.is_primal_feasible():
                            primary["objective"] = model.solution.get_objective_value()
                            incumbent = candidate_from_values(
                                model.variables.get_names(), model.solution.get_values(),
                                snapshot["duals"], geometry,
                                coefficients=model.objective.get_linear(),
                                reported_objective=primary["objective"])
                        try:
                            primary["bound"] = model.solution.MIP.get_best_objective()
                        except cplex.exceptions.CplexError:
                            pass
                        row = dict(strategy=strategy, iteration=snapshot["iteration"],
                                   primary=primary, primary_time_s=solve_s,
                                   populate_time_s=0.0, populate_limit_s=0.0,
                                   populate_status=None, mip_starts=model.MIP_starts.get_num(),
                                   advance=model.parameters.advance.get())
                        closed = (primary["bound"] is not None and primary["bound"] <= 1e-9)
                        if strategy == "populate" and not closed:
                            requested = min(args.populate_time, args.populate_ratio * solve_s,
                                            replay_deadline - time.perf_counter())
                            if requested > 0:
                                model.parameters.mip.limits.populate.set(args.populate_limit)
                                model.parameters.timelimit.set(requested)
                                begin = time.perf_counter()
                                model.populate_solution_pool()
                                row.update(populate_time_s=time.perf_counter() - begin,
                                           populate_limit_s=requested,
                                           populate_status=model.solution.get_status())
                        begin = time.perf_counter()
                        read = read_solution_pool(
                            model, snapshot["duals"], geometry, snapshot["known_keys"],
                            incumbent, max_extra=args.batch_size - 1)
                        row.update(asdict(read))
                        row.pop("candidates")
                        row["extraction_time_s"] = time.perf_counter() - begin
                        report["replays"].append(row)
                        persist(args.result, report)
                finally:
                    session.close()
            report["snapshots"] = [dict(
                iteration=snapshots[index]["iteration"], duals=snapshots[index]["duals"],
                known_keys=sorted(snapshots[index]["known_keys"])) for index in chosen]
        report["complete"] = True
    except Exception as error:
        report["error"] = f"{type(error).__name__}: {error}"
    finally:
        persist(args.result, report)


def summarize(folder, runs):
    lines = ["# Pricing pool preflight", "",
             "Diagnostic only: extras were never added to the master. Offline replay costs",
             "are separate from the baseline trajectory. This does not establish a CG speedup.", "",
             "| Case | Mode | Seed | Repeat | LP | IP | Closed | Calls | Raw pool median | Useful extra total | Wall (s) | Error |",
             "|---|---|---:|---:|---:|---:|---|---:|---:|---:|---:|---|"]
    for run in runs:
        baseline = run.get("baseline") or {}
        m, d = baseline.get("metrics", {}), baseline.get("diagnostics", {})
        observations = run.get("observations", [])
        counts = [row["raw_count"] for row in observations if "raw_count" in row]
        lines.append("| " + " | ".join(str(value) for value in (
            run["case"], run["mode"], run["seed"], run["repeat"],
            m.get("lp_value"), m.get("restricted_integer_master"),
            d.get("lp_convergence_proven"), len(observations),
            statistics.median(counts) if counts else "NA",
            sum(row.get("useful_extra", 0) for row in observations),
            round(run.get("baseline_wall_s", 0), 4), run.get("error") or "")) + " |")
    pairs = []
    for observed in (run for run in runs if run["mode"] == "observe"):
        control = next((run for run in runs if run["mode"] == "control" and all(
            run[key] == observed[key] for key in ("case", "seed", "repeat"))), None)
        if control is not None:
            fields = ("lp_value", "restricted_integer_master", "cg_iterations", "generated_columns")
            match = (not control.get("error") and not observed.get("error")
                     and control.get("complete") and observed.get("complete")
                     and all(control["baseline"]["metrics"][key] ==
                             observed["baseline"]["metrics"][key] for key in fields)
                     and [row["primary_key_hash"] for row in control["observations"]] ==
                         [row["primary_key_hash"] for row in observed["observations"]])
            pairs.append(dict(case=observed["case"], seed=observed["seed"],
                              repeat=observed["repeat"], trajectory_match=bool(match)))
    persist(folder / "trajectory_checks.json", pairs)
    lines += ["", f"Exact trajectory checks: {sum(pair['trajectory_match'] for pair in pairs)}/{len(pairs)} pairs.",
              "Full candidate counters, primary evidence, replay limits and dual snapshots are in each JSON.",
              "Unmatched or incomplete pairs cannot establish observation neutrality.",
              "A small or empty pool at intensity 1 is not a rejection of deliberate populate search."]
    (folder / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", nargs="+", default=["case1", "IB_004", "case18"])
    parser.add_argument("--seeds", nargs="+", type=int, default=[1])
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--time", type=float, default=60)
    parser.add_argument("--replay-time", type=float, default=30)
    parser.add_argument("--wall-timeout", type=float, default=100)
    parser.add_argument("--capacity", type=int, default=20)
    parser.add_argument("--batch-size", type=int, default=5)
    parser.add_argument("--populate-limit", type=int, default=20)
    parser.add_argument("--populate-time", type=float, default=0.1)
    parser.add_argument("--populate-ratio", type=float, default=0.1)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--case", help=argparse.SUPPRESS)
    parser.add_argument("--seed", type=int, default=1, help=argparse.SUPPRESS)
    parser.add_argument("--mode", choices=["control", "observe"], help=argparse.SUPPRESS)
    parser.add_argument("--result", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if (args.repeats < 1 or args.capacity < 1 or args.batch_size < 1 or args.populate_limit < 1
            or any(seed < 0 for seed in args.seeds) or any(
                not math.isfinite(value) or value <= 0 for value in (
                    args.time, args.replay_time, args.wall_timeout,
                    args.populate_time, args.populate_ratio))):
        parser.error("counts and finite budgets must be positive; seeds must be nonnegative")
    if any(name not in catalog() for name in args.cases):
        parser.error("unknown case; use a catalog case or benchmark baseline instance")
    if args.mode:
        if not args.result or args.case not in catalog():
            parser.error("worker requires a valid case and result path")
        worker(args)
        return 0
    folder = (args.output or ROOT / "Results" / datetime.now().strftime(
        "pricing_pool_preflight_%Y%m%d_%H%M%S_%f")).resolve()
    folder.mkdir(parents=True, exist_ok=False)
    import cplex
    sources = ["models/column_generation/solution_pool.py",
               "models/column_generation/slave_problem.py",
               "models/column_generation/column_generation_solver.py", Path(__file__).name]
    manifest = dict(recorded_at=datetime.now(timezone.utc).isoformat(), python=sys.version,
                    cplex=cplex.__version__, platform=platform.platform(), parameters={
                        key: str(value) if isinstance(value, Path) else value
                        for key, value in vars(args).items()}, sha256={
                            name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
                            for name in sources})
    persist(folder / "manifest.json", manifest)
    runs = []
    for case in args.cases:
        for seed in args.seeds:
            for repeat in range(1, args.repeats + 1):
                for mode in (("control", "observe") if repeat % 2 else ("observe", "control")):
                    result = folder / f"{case}_{seed}_{repeat}_{mode}.json"
                    command = [sys.executable, str(Path(__file__).resolve()), "--mode", mode,
                               "--case", case, "--seed", str(seed), "--result", str(result)]
                    for option in ("time", "replay_time", "capacity", "batch_size",
                                   "populate_limit", "populate_time", "populate_ratio"):
                        command += ["--" + option.replace("_", "-"), str(getattr(args, option))]
                    try:
                        completed = subprocess.run(
                            command, cwd=ROOT, capture_output=True, text=True,
                            timeout=args.wall_timeout,
                            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
                        error = completed.stderr[-2000:] if completed.returncode else None
                    except subprocess.TimeoutExpired:
                        error = "ExternalTimeout; persisted partial observations retained"
                    run = json.loads(result.read_text(encoding="utf-8")) if result.exists() else {}
                    run.update(case=case, seed=seed, repeat=repeat, mode=mode)
                    if error:
                        run["error"] = error
                    persist(result, run)
                    runs.append(run)
                    summarize(folder, runs)
                    print(f"{case} seed={seed} repeat={repeat} {mode}: "
                          f"{run.get('error') or 'complete'}", flush=True)
    print(f"Report: {folder / 'summary.md'}")
    current_hashes = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
                      for name in sources}
    manifest["source_changed_during_run"] = current_hashes != manifest["sha256"]
    manifest["final_sha256"] = current_hashes
    persist(folder / "manifest.json", manifest)
    if manifest["source_changed_during_run"]:
        print("Sources changed during this run: exploratory data only, rerun before freezing settings.")
    return int(manifest["source_changed_during_run"] or any(run.get("error") for run in runs))


if __name__ == "__main__":
    raise SystemExit(main())
