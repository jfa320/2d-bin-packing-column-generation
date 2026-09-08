import csv
import subprocess
import sys

import pytest

import benchmark_runner as runner
from utils.execution_result import (
    ColumnGenerationExecutionResult, ColumnGenerationMetrics, ExecutionResult,
)


def write_input(path, count=30, changes=None):
    rows = [dict(zip(runner.INPUT_FIELDS,
                    (f"sample_{i}", "family", 20, 10, 4, 2, 25, "paper")))
            for i in range(count)]
    if changes:
        rows[0].update(changes)
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=runner.INPUT_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    return path


def make_result(ip=25, lp=25, termination="Normal", error=None):
    return ColumnGenerationExecutionResult(
        ExecutionResult("sample", "Model5Orchestrator", 8, termination, ip, 3.5,
                        error_message=error),
        ColumnGenerationMetrics(lp, ip, 3, 7, 2.5, 1.0),
    )


def read_report(path):
    with path.open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        assert reader.fieldnames == list(runner.OUTPUT_FIELDS)
        return list(reader)


def test_all_csv_rows_order_flags_dimensions_metrics_and_flush(tmp_path):
    source = write_input(tmp_path / "input.csv", 77)
    output = tmp_path / "report.csv"
    calls = []

    def execute(max_time, instance, finalization_heuristics):
        assert len(read_report(output)) == len(calls)
        assert max_time == 12
        assert finalization_heuristics is False
        assert instance == {"case_name": f"sample_{len(calls)}", "bin_width": 20,
                            "bin_height": 10, "item_width": 4, "item_height": 2}
        calls.append(instance)
        return make_result()

    assert runner.run_benchmark(source, output, max_time=12, execute=execute) == output.resolve()
    rows = read_report(output)
    assert len(rows) == len(calls) == 77
    assert [row["instance"] for row in rows] == [f"sample_{i}" for i in range(77)]
    assert runner.OUTPUT_FIELDS == (
        "instance", "family", "L", "W", "l", "w", "optimal_literature",
        "lp_value", "restricted_integer_master", "cg_iterations", "generated_columns",
        "cg_time_s", "integer_master_time_s", "total_time_s", "gap_percent", "status",
        "source", "error_message",
    )
    assert rows[0]["cg_iterations"] == "3"
    assert rows[0]["generated_columns"] == "7"
    assert rows[0]["cg_time_s"] == "2.500000"
    assert rows[0]["integer_master_time_s"] == "1.000000"
    assert rows[0]["total_time_s"] == "3.500000"
    assert rows[0]["optimal_literature"] == "25.000000"
    assert rows[0]["error_message"] == "NA"
    assert rows[0]["status"] == "OPTIMAL"
    assert rows[0]["gap_percent"] == "0.000000"


def test_exception_and_invalid_contract_continue_with_structured_trace(tmp_path, monkeypatch):
    source = write_input(tmp_path / "input.csv", 3)
    trace = tmp_path / "trace.trc"
    results = []

    class TraceStub:
        def __init__(self, filename, mode, directory):
            assert filename == str(trace.resolve())
            assert mode == "overwrite"
            assert directory == "Results"

        def write_trace_record(self, result):
            assert isinstance(result, ColumnGenerationExecutionResult)
            results.append(result)

    import utils.trace_file_generator as trace_module
    monkeypatch.setattr(trace_module, "TraceFileGenerator", TraceStub)

    def execute(*args, **kwargs):
        name = kwargs["instance"]["case_name"]
        if name == "sample_0":
            raise RuntimeError("failed, with diagnostic\nand newline")
        if name == "sample_1":
            return None
        return make_result()

    output = runner.run_benchmark(source, tmp_path / "report.csv", expected_count=3,
                                  trace_path=trace, execute=execute)
    rows = read_report(output)
    assert len(rows) == len(results) == 3
    assert rows[0]["status"] == "LP_FAIL"
    assert rows[0]["gap_percent"] == rows[0]["restricted_integer_master"] == rows[0]["lp_value"] == "NA"
    assert rows[0]["error_message"] == "RuntimeError: failed, with diagnostic\nand newline"
    assert results[0].execution.termination_status == "Error"
    assert results[0].execution.model_name == "Model5Orchestrator"
    assert results[0].execution.model_status == 13
    assert results[1].execution.model_name == "Model5Orchestrator"
    assert results[1].execution.model_status == 13
    assert results[0].execution.objective_value is None
    assert results[0].execution.total_time_s >= 0
    assert "TypeError" in rows[1]["error_message"]
    assert rows[2]["status"] == "OPTIMAL"


@pytest.mark.parametrize("ip,lp,termination,error,status,gap", [
    (26, None, "TimeLimit", "error", "REFERENCE_EXCEEDED", -4),
    (25, 25, "TimeLimit", None, "TIMEOUT_FEASIBLE", 0),
    (20, 25, "TimeLimit", None, "TIMEOUT_FEASIBLE", 20),
    (None, None, "TimeLimit", None, "TIMEOUT_NO_SOLUTION", None),
    (None, 25, "TimeLimit", None, "TIMEOUT_NO_SOLUTION", None),
    (None, None, "Error", "failed", "LP_FAIL", None),
    (None, 25, "Error", "failed", "LP_OK_IP_FAIL", None),
    (25, 25, "Error", "failed", "ERROR", 0),
    (25, 25, "NodeLimit", None, "ERROR", 0),
    (25, 25, "Normal", "failed", "ERROR", 0),
    (25, 25, "Normal", None, "OPTIMAL", 0),
    (20, 25, "Normal", None, "SUBOPTIMAL", 20),
    (0, 25, "Normal", None, "SUBOPTIMAL", 100),
])
def test_status_precedence_and_maximization_gap(ip, lp, termination, error, status, gap):
    row = runner.result_row({"optimal_literature": 25}, make_result(ip, lp, termination, error))
    assert row["status"] == status
    assert row["gap_percent"] == gap


@pytest.mark.parametrize("ip,termination,status,gap", [
    (26.0, "Normal", "REFERENCE_EXCEEDED", "-4.000000"),
    (20.0, "TimeLimit", "TIMEOUT_FEASIBLE", "20.000000"),
    (25.0, "Error", "ERROR", "0.000000"),
])
def test_csv_signed_gap_status_and_float_format(tmp_path, ip, termination, status, gap):
    source = write_input(tmp_path / "input.csv", 1)
    result = make_result(ip=ip, lp=26.123456789, termination=termination)
    result.metrics.cg_time_s = 0.0000001
    output = runner.run_benchmark(source, tmp_path / "out.csv", expected_count=1,
                                  execute=lambda *a, **k: result)
    row = read_report(output)[0]
    assert row["status"] == status
    assert row["gap_percent"] == gap
    assert row["lp_value"] == "26.123457"
    assert row["restricted_integer_master"] == f"{ip:.6f}"
    assert row["cg_time_s"] == "0.000000"
    assert row["error_message"] == "NA"


def test_real_trace_writer(tmp_path):
    source = write_input(tmp_path / "input.csv", 2)
    trace = tmp_path / "trace.trc"

    def execute(*args, **kwargs):
        if kwargs["instance"]["case_name"] == "sample_0":
            raise RuntimeError("trace error")
        result = make_result()
        result.execution.case_name = "sample_1"
        return result

    output = runner.run_benchmark(source, tmp_path / "out.csv", expected_count=2,
                                  trace_path=trace, execute=execute)
    with trace.open(newline="", encoding="utf-8") as stream:
        records = list(csv.reader(line for line in stream if not line.startswith("*")))
    assert len(records) == 2
    assert all(len(record) == 8 for record in records)
    assert records[0][:6] == ["sample_0", "Model5Orchestrator", "1", "13", "Error", "NA"]
    assert float(records[0][6]) >= 0
    assert records[0][7] == "0"
    assert records[1] == ["sample_1", "Model5Orchestrator", "1", "8", "Normal", "25", "3.500000", "3"]
    assert len(read_report(output)) == 2


@pytest.mark.parametrize("field,value", [
    (field, value) for field in ("L", "W", "l", "w")
    for value in ("0", "-1", "1.5", "nan", "", "True")
] + [(field, " ") for field in ("instance", "family", "source")]
  + [("optimal_literature", value) for value in ("0", "-1", "nan", "inf", "", "abc")])
def test_invalid_values(tmp_path, field, value):
    source = write_input(tmp_path / "input.csv", 1, {field: value})
    with pytest.raises(ValueError, match=field):
        runner.load_instances(source, 1)


def test_count_duplicate_ids_and_missing_headers(tmp_path):
    source = write_input(tmp_path / "input.csv", 2)
    assert len(runner.load_instances(source)) == 2
    write_input(source, 2, {"instance": " sample_1 "})
    with pytest.raises(ValueError, match="duplicate instance"):
        runner.load_instances(source, 2)
    source.write_text("instance,family\na,b\n", encoding="utf-8")
    with pytest.raises(ValueError, match="headers"):
        runner.load_instances(source, 1)


@pytest.mark.parametrize("collision", ["existing_output", "existing_trace", "input_output", "input_trace", "output_trace"])
def test_protect_outputs_and_paths(tmp_path, collision):
    source = write_input(tmp_path / "input.csv", 1)
    output, trace = tmp_path / "out.csv", tmp_path / "trace.trc"
    if collision == "existing_output":
        output.write_text("keep", encoding="utf-8")
    elif collision == "existing_trace":
        trace.write_text("keep", encoding="utf-8")
    elif collision == "input_output":
        output = source
    elif collision == "input_trace":
        trace = source
    else:
        trace = output
    before = {path: path.read_bytes() for path in (source, output, trace) if path.exists()}

    def forbidden(*args, **kwargs):
        pytest.fail("Solver must not run")

    with pytest.raises((ValueError, FileExistsError)):
        runner.run_benchmark(source, output, expected_count=1, trace_path=trace, execute=forbidden)
    assert all(path.read_bytes() == contents for path, contents in before.items())


def test_cli_defaults_and_smoke_override(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(runner, "run_benchmark", lambda *args, **kwargs: calls.append((args, kwargs)) or tmp_path)
    assert runner.main([]) == 0
    assert calls[0][0] == (runner.DEFAULT_INPUT, None)
    assert calls[0][1]["expected_count"] is None
    assert runner.main(["--input", "small.csv", "--expected-count", "2", "--time", "5",
                        "--output", "out.csv", "--trace", "out.trc"]) == 0
    assert calls[1] == (("small.csv", "out.csv"),
                        {"max_time": 5, "expected_count": 2, "trace_path": "out.trc"})


def test_default_output_and_lazy_import(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    source = write_input(tmp_path / runner.DEFAULT_INPUT, 1)
    output = runner.run_benchmark(source, expected_count=1, execute=lambda *a, **k: make_result())
    assert output.parent == tmp_path / "Results"
    assert output.name.startswith("benchmark_") and output.suffix == ".csv"


@pytest.mark.parametrize("contents", [
    ",".join(runner.INPUT_FIELDS) + ",instance\na,b,20,10,4,2,25,paper,a\n",
    ",".join(runner.INPUT_FIELDS) + "\na,b,20,10,4,2,25\n",
    ",".join(runner.INPUT_FIELDS) + "\na,b,20,10,4,2,25,paper,extra\n",
])
def test_malformed_input_creates_no_outputs(tmp_path, contents):
    source = tmp_path / "input.csv"
    source.write_text(contents, encoding="utf-8")
    output, trace = tmp_path / "report.csv", tmp_path / "trace.trc"
    with pytest.raises(ValueError):
        runner.run_benchmark(source, output, expected_count=1, trace_path=trace)
    assert not output.exists()
    assert not trace.exists()


@pytest.mark.parametrize("count", [0, -1, True, 1.5])
def test_invalid_expected_count(tmp_path, count):
    source = write_input(tmp_path / "input.csv", 1)
    with pytest.raises(ValueError, match="expected_count"):
        runner.load_instances(source, count)


@pytest.mark.parametrize("limit", [0, -1, float("nan"), float("inf")])
def test_invalid_time_limit(tmp_path, limit):
    with pytest.raises(ValueError, match="max_time"):
        runner.run_benchmark(tmp_path / "absent.csv", max_time=limit)


def test_import_does_not_load_solver():
    subprocess.run([sys.executable, "-c",
                    "import sys; import benchmark_runner; "
                    "assert 'cplex' not in sys.modules; "
                    "assert 'models.column_generation.column_generation_solver' not in sys.modules"],
                   check=True, timeout=20)
