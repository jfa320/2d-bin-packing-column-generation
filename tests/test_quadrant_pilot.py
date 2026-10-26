"""Pilot accounting/protocol checks; these tests do not solve optimization models."""

import csv
import json
from pathlib import Path
from types import SimpleNamespace
import subprocess
from unittest.mock import Mock

import pytest

import quadrant_pilot as pilot
from models.quadrant_column_generation.configuration import Placement, QuadrantConfiguration
from models.quadrant_column_generation.master_problem import RestrictedMasterResult
from models.quadrant_column_generation.pricing_problem import PricingResult
from models.quadrant_column_generation.quadrants import build_quadrants
from models.quadrant_column_generation.root_solver import CGStatus, EPS, RootCGResult, RootIteration, RootPricingRecord
from utils.status_normalizer import map_cplex_lp_status, map_cplex_mip_status


@pytest.fixture
def instance():
    return dict(instance="tiny", family="control", L=6, W=6, l=1, w=1,
                optimal_literature=36.0, source="manual area and unit-grid tiling")


@pytest.fixture
def result():
    quadrant = build_quadrants(6, 6, 1, 1).quadrants[0]
    configuration = QuadrantConfiguration(quadrant, (Placement(0, 0, 1, 1),))
    pricing = PricingResult(configuration, 1.0, 0.0, map_cplex_mip_status(101),
                            True, 1.0, 0.0, 0.3, 0.5, 1.0, EPS,
                            closure_proven=True, closure_basis="optimal_pricing", raw_cplex_status=101)
    master = RestrictedMasterResult(36.0, {}, map_cplex_lp_status(1, True), True,
                                    None, 0.1, 5, raw_cplex_status=1)
    iteration = RootIteration(
        1, 4, 4, 5, rmp=master, sigma={1: 1.0, 2: 0.0, 3: 0.0, 4: 0.0},
        pricings=[RootPricingRecord(1, 4, 59.0, pricing, 0.5, True, True)],
        columns_found=[configuration], columns_added=[configuration],
        rmp_wall_time_s=0.1, pricing_wall_time_s=0.5, column_update_time_s=0.05,
    )
    return RootCGResult(CGStatus.CONVERGED, "four_current_pricing_certificates", 36.0,
                        master, (configuration,) * 5, (iteration,), 5, True, 0.9, False)


def test_baseline_applicability_is_exact_and_unchanged():
    rows = pilot.load_instances(Path(pilot.ROOT) / "benchmark_validation_baseline.csv")
    names = [row["instance"] for row in rows if pilot.base_row(row, 60)[1].applicable]
    assert len(rows) == 30
    assert names == ["IB_010", "IIIB_001", "IIIB_002", "IIIB_003", "IIIB_004",
                     "IIIB_006", "IIIB_008", "IIIB_009"]


@pytest.mark.parametrize("size,applicable", [(5, False), (6, True)])
def test_strict_boundary(instance, size, applicable):
    instance.update(L=size, W=size)
    assert pilot.base_row(instance, 60)[0]["applicable"] is applicable


def test_nonapplicable_never_starts_worker(monkeypatch, instance):
    instance.update(W=5)
    process = Mock()
    monkeypatch.setattr(pilot.subprocess, "run", process)
    payload = pilot.run_one(instance, 60)
    assert payload["row"]["status"] == "NOT_APPLICABLE"
    assert payload["row"]["applicable"] is False
    assert not payload["row"].get("error_message")
    assert payload["iterations"] == payload["pricings"] == []
    process.assert_not_called()


@pytest.mark.parametrize("kind,expected", [("proof", "CONVERGED"), ("timeout", "TIMEOUT"),
                                         ("inconclusive", "INCONCLUSIVE"), ("error", "ERROR")])
def test_status_and_gaps(instance, result, kind, expected):
    from dataclasses import replace
    if kind != "proof":
        result = replace(result, status=CGStatus.INCONCLUSIVE,
                         stop_reason="global_deadline" if kind == "timeout" else "pricing_inconclusive",
                         had_timeouts=kind == "timeout", error_message="failure" if kind == "error" else None)
    row = pilot.project(instance, 60, result, dict(build=0.1, solve=0.2, update=0.05, close=0.05))["row"]
    assert row["status"] == expected
    assert row["lp_value"] == 36
    assert row["lp_gap_percent"] == (0.0 if kind == "proof" else None)
    assert row["lp_convergence_proven"] is (kind == "proof")


def test_accounting_and_signed_lp_gap(instance, result):
    instance["optimal_literature"] = 35.0
    payload = pilot.project(instance, 60, result, dict(build=0.1, solve=0.2, update=0.05, close=0.05))
    row = payload["row"]
    assert row["master_lp_time_s"] == pytest.approx(0.4)
    assert row["pricing_time_s"] == 0.5
    assert row["pricing_solve_time_s"] == 0.3
    assert row["initial_columns"] == 4
    assert row["generated_columns"] == 1
    assert row["final_columns"] == 5
    assert row["duplicates"] == 0
    assert row["cg_iterations"] == row["pricing_calls"] == 1
    assert row["lp_gap_percent"] == pytest.approx(-100 / 35)
    assert row["lp_excess_percent"] == pytest.approx(100 / 35)
    assert payload["pricings"][0]["raw_cplex_status"] == 101
    assert payload["iterations"][0]["sigma"] == '{"1": 1.0, "2": 0.0, "3": 0.0, "4": 0.0}'


def test_timeout_does_not_erase_a_valid_closure(result):
    from dataclasses import replace
    assert pilot.classify(replace(result, had_timeouts=True)) == "CONVERGED"
    assert pilot.classify(replace(result, lp_is_current=False)) == "INCONCLUSIVE"


def test_external_timeout_leaves_unknown_metrics(monkeypatch, instance):
    process = Mock(side_effect=subprocess.TimeoutExpired("worker", 75))
    monkeypatch.setattr(pilot.subprocess, "run", process)
    payload = pilot.run_one(instance, 60, 15)
    row = payload["row"]
    assert row["status"] == "TIMEOUT" and row["had_timeouts"]
    assert row["cg_stop_reason"] == "external_timeout"
    assert row.get("master_lp_time_s") is None
    assert row.get("lp_value") is None
    assert process.call_args.kwargs["timeout"] == 75
    assert process.call_args.kwargs["cwd"] == pilot.ROOT


def test_worker_error_is_distinct_from_nonconvergence(monkeypatch, instance):
    monkeypatch.setattr(pilot.subprocess, "run", Mock(return_value=SimpleNamespace(
        returncode=1, stderr="CPLEX exception", stdout="")))
    row = pilot.run_one(instance, 60)["row"]
    assert row["status"] == "ERROR"
    assert "CPLEX exception" in row["error_message"]


def test_master_instrumentation_delegates_and_restores(monkeypatch):
    inner = SimpleNamespace(solve=Mock(return_value="answer"),
                            add_configuration=Mock(return_value="column"), close=Mock(),
                            cplex_model=object(), model_revision=4)
    builder = SimpleNamespace(quadrants=(1, 2, 3, 4), build=Mock(return_value=inner))
    original = Mock(return_value=builder)
    module = SimpleNamespace(RestrictedMasterBuilder=original)
    clock = iter(range(8))
    monkeypatch.setattr(pilot.time, "perf_counter", lambda: next(clock))
    totals = dict.fromkeys(("build", "solve", "update", "close"), 0.0)
    with pilot.measure_master(module, totals):
        wrapped = module.RestrictedMasterBuilder("grid", "quadrants")
        master = wrapped.build(["empty"], time_limit_s=12)
        assert master.cplex_model is inner.cplex_model
        assert master.solve() == "answer"
        assert master.add_configuration("config") == "column"
        master.close()
    assert module.RestrictedMasterBuilder is original
    assert totals == dict.fromkeys(("build", "solve", "update", "close"), 1.0)
    original.assert_called_once_with("grid", "quadrants")
    builder.build.assert_called_once_with(["empty"], time_limit_s=12)
    inner.add_configuration.assert_called_once_with("config")


def test_master_observer_preserves_return_and_model(monkeypatch):
    result = object()
    inner = SimpleNamespace(solve=Mock(return_value=result))
    builder = SimpleNamespace(quadrants=(1, 2, 3, 4), build=Mock(return_value=inner))
    module = SimpleNamespace(RestrictedMasterBuilder=Mock(return_value=builder))
    totals = dict.fromkeys(("build", "solve", "update", "close"), 0.0)
    observer = Mock()
    with pilot.measure_master(module, totals, observer):
        master = module.RestrictedMasterBuilder().build()
        assert master.solve() is result
    observer.assert_called_once_with(inner, result)


def test_progress_is_opt_in_and_keeps_full_precision(monkeypatch, tmp_path):
    monkeypatch.delenv("QUADRANT_PILOT_PROGRESS_DIR", raising=False)
    with pilot.progress_sink({"instance": "case"}, 0, {}) as observer:
        assert observer is None
    assert list(tmp_path.iterdir()) == []
    monkeypatch.setenv("QUADRANT_PILOT_PROGRESS_DIR", str(tmp_path))
    result = SimpleNamespace(duals=SimpleNamespace(sigma={1: 0.123456789}),
                             model_revision=4, objective_value=49.123456789,
                             proven_optimal=True, raw_cplex_status=1)
    master = SimpleNamespace(configurations=(1, 2, 3, 4))
    before = dict(vars(result))
    with pilot.progress_sink({"instance": "../case"}, 0, {"solve": 0.5}) as observer:
        observer(master, result)
        observer(master, result)
    files = list(tmp_path.glob("*.jsonl"))
    assert len(files) == 1
    records = [json.loads(line) for line in files[0].read_text().splitlines()]
    assert [r["rmp_solve"] for r in records] == [1, 2]
    assert records[0]["lp_value"] == 49.123456789
    assert records[0]["sigma"] == {"1": 0.123456789}
    assert records[0]["pool_size"] == 4
    assert vars(result) == before
    with pytest.raises(FileExistsError):
        with pilot.progress_sink({"instance": "../case"}, 0, {}):
            pass


def test_csv_reports_all_rows_and_protects_artifacts(tmp_path, monkeypatch, instance):
    source, output = tmp_path / "input.csv", tmp_path / "pilot.csv"
    source.write_text("instance,family,L,W,l,w,optimal_literature,source\n"
                      "tiny,control,6,6,1,1,36,manual\n", encoding="utf-8")
    monkeypatch.setattr(pilot, "metadata", lambda *args: {"time_limit_s": 60})
    monkeypatch.setattr(pilot, "run_one", lambda *args: dict(
        row={**instance, "alpha": 0.8, "applicable": True, "status": "INCONCLUSIVE",
             "total_time_s": 0.12345678}, iterations=[], pricings=[]))
    assert pilot.run_pilot(source, output) == output
    with output.open(newline="", encoding="utf-8") as stream:
        row = next(csv.DictReader(stream))
    assert row["lp_value"] == row["lp_gap_percent"] == "NA"
    assert row["total_time_s"] == "0.123457"
    assert json.loads(output.with_suffix(".json").read_text())["time_limit_s"] == 60
    assert output.with_name("pilot_iterations.csv").exists()
    assert output.with_name("pilot_pricing.csv").exists()
    with pytest.raises(FileExistsError):
        pilot.run_pilot(source, output)


@pytest.mark.parametrize("limit", [0, -1, float("nan"), float("inf")])
def test_invalid_budgets_create_no_files(tmp_path, limit):
    with pytest.raises(ValueError):
        pilot.run_pilot(tmp_path / "input.csv", tmp_path / "out.csv", limit=limit)
    assert list(tmp_path.iterdir()) == []
