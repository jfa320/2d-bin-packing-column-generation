import time
import csv
from queue import Queue

import pytest
from utils.iteration_report import report_paths

from models.column_generation.column_generation_solver import orchestrator
from objects.ConfigData import ConfigData


CASES = [
    ("case1", (6, 4, 2, 3), 4),
    ("case2", (5, 5, 3, 2), 4),
    ("case3", (6, 6, 4, 2), 4),
    ("case4", (7, 3, 3, 2), 3),
    ("case5", (6, 3, 3, 2), 3),
    ("case6", (120, 20, 12, 8), 25),
    ("case7", (50, 20, 13, 8), 7),
    ("case8", (40, 25, 10, 6), 16),
    ("case9", (60, 20, 12, 7), 13),
    ("case10", (45, 30, 9, 9), 15),
    ("case11", (70, 25, 14, 8), 15),
    ("case12", (55, 22, 11, 6), 18),
    ("case13", (20, 20, 6, 5), 12),
    ("case14", (40, 30, 10, 7), 16),
    ("case15", (60, 25, 12, 5), 25),
    ("case16", (48, 24, 8, 6), 24),
    ("case17", (70, 28, 14, 7), 20),
    ("case18", (10, 30, 1, 6), 50),
]


@pytest.mark.parametrize("case_name, dimensions, expected", CASES, ids=[case[0] for case in CASES])
def test_orchestrator_cases(orchestrator_context, case_name, dimensions, expected):
    queue, manual_interruption, execution_time = orchestrator_context
    config_data = ConfigData(*dimensions)

    objective_value = orchestrator(
        queue, manual_interruption, execution_time, time.time(), config_data,
        case_name=case_name,
    )

    assert objective_value == expected


@pytest.mark.parametrize("heuristics", [False, True], ids=["base", "heuristics"])
def test_case1_structured_phase_metrics(heuristics):
    result = orchestrator(
        Queue(), None, 30, time.perf_counter(), ConfigData(6, 4, 2, 3),
        case_name=f"instrumentation_case1_{heuristics}", return_structured=True,
        finalization_heuristics=heuristics,
    )
    metrics, diagnostics = result.metrics, result.diagnostics
    assert result.execution.objective_value == 4
    assert result.execution.termination_status == "Normal"
    assert metrics.master_lp_time_s > 0
    assert metrics.pricing_time_s > 0
    assert metrics.integer_master_time_s > 0
    assert metrics.master_lp_time_s + metrics.pricing_time_s <= metrics.cg_time_s
    assert metrics.cg_time_s + metrics.integer_master_time_s <= result.execution.total_time_s
    assert diagnostics.cg_stop_reason == "pricing_converged"
    assert diagnostics.lp_convergence_proven
    assert diagnostics.pricing_status.raw_cplex_status == 101
    assert diagnostics.integer_master_status.raw_cplex_status == 101
    assert diagnostics.active_phase is None
    assert len(result.iterations) == metrics.cg_iterations
    assert all(row.completed for row in result.iterations)
    assert [row.iteration for row in result.iterations] == list(range(1, len(result.iterations) + 1))
    for field in ("master_lp_time_s", "pricing_time_s", "master_build_time_s",
                  "master_solve_time_s", "pricing_build_time_s", "pricing_solve_time_s"):
        assert sum(getattr(row, field) for row in result.iterations) == pytest.approx(getattr(metrics, field))
    assert metrics.master_build_time_s > 0
    assert metrics.master_solve_time_s > 0
    assert metrics.pricing_build_time_s > 0
    assert metrics.pricing_solve_time_s > 0
    if heuristics:
        assert diagnostics.auxiliary_pricing_status.raw_cplex_status is not None


@pytest.mark.parametrize("detailed_csv", [False, True], ids=["summary", "detailed"])
def test_spawned_case1_benchmark_exports_phase_diagnostics(tmp_path, detailed_csv):
    from benchmark_runner import run_benchmark

    source = tmp_path / "case1.csv"
    source.write_text(
        "instance,family,L,W,l,w,optimal_literature,source\n"
        "instrumentation_spawn_case1,smoke,6,4,2,3,4,fixture\n",
        encoding="utf-8",
    )
    trace = tmp_path / "case1.trc"
    output = run_benchmark(source, tmp_path / "report.csv", trace_path=trace, max_time=30,
                           detailed_csv=detailed_csv)
    with output.open(newline="", encoding="utf-8") as stream:
        row = next(csv.DictReader(stream))
    assert float(row["restricted_integer_master"]) == 4
    assert row["status"] == "OPTIMAL"
    assert row["cg_stop_reason"] == "pricing_converged"
    assert row["lp_convergence_proven"] == "True"
    assert row["integer_master_model_status"] == "1"
    assert float(row["master_lp_time_s"]) > 0
    assert float(row["pricing_time_s"]) > 0
    if detailed_csv:
        assert len(row) == 44
        assert row["pricing_phase2_raw_cplex_status"] == "NA"
    else:
        assert len(row) == 24
        assert "pricing_phase2_raw_cplex_status" not in row
    records = [line for line in trace.read_text().splitlines() if not line.startswith("*")]
    assert len(records) == 1
    assert len(records[0].split(",")) == 8
    iterations_path, phases_path = report_paths(output)
    with iterations_path.open(newline="", encoding="utf-8") as stream:
        iterations = list(csv.DictReader(stream))
    with phases_path.open(newline="", encoding="utf-8") as stream:
        phases = list(csv.DictReader(stream))
    assert len(iterations) == int(row["cg_iterations"])
    assert len(phases) == 1
    assert iterations[-1]["stop_reason"] == "pricing_converged"
    assert all(item["completed"] == "True" for item in iterations)
    assert all(int(item["pool_after"]) == int(item["pool_before"]) + int(item["generated_columns"])
               for item in iterations)
    assert float(phases[0]["master_solve_time_s"]) > 0
    assert float(phases[0]["pricing_solve_time_s"]) > 0
    assert float(phases[0]["pricing_percent_cg"]) > 0
    assert float(phases[0]["pricing_percent_total"]) > 0
