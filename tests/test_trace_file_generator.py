from pathlib import Path

import pytest

from utils.execution_result import ColumnGenerationExecutionResult, ColumnGenerationMetrics, ExecutionResult
from utils.trace_file_generator import TraceFileGenerator


def execution(case="IB_001", model="Model5Orchestrator", **kwargs):
    values = dict(model_status=8, termination_status="Normal",
                  objective_value=5, total_time_s=1.25)
    values.update(kwargs)
    return ExecutionResult(case, model, **values)


def test_trace_has_paver_definition_and_serializes_missing_values(tmp_path):
    writer = TraceFileGenerator("run.trc", directory=str(tmp_path))
    writer.write_trace_record(ColumnGenerationExecutionResult(
        execution("IB_001"), ColumnGenerationMetrics(cg_iterations=3)))
    writer.write_trace_record(execution("IB_002", "Model1Rotation",
                                        model_status=9, termination_status="TimeLimit",
                                        objective_value=None))

    lines = (tmp_path / "run.trc").read_text(encoding="utf-8").splitlines()
    assert lines[1].endswith("TerminationStatus,ObjectiveValue,SolverTime,NumberOfIterations")
    assert lines[2].endswith(",8,Normal,5,1.250000,3")
    assert lines[3].endswith(",9,TimeLimit,NA,1.250000,NA")
    assert "SolverStatus" not in lines[1]
    assert "105" not in lines[3]


def test_trace_rejects_duplicate_and_ambiguous_model(tmp_path):
    writer = TraceFileGenerator("run.trc", directory=str(tmp_path))
    writer.write_trace_record(execution())
    with pytest.raises(ValueError, match="Duplicate"):
        writer.write_trace_record(execution())
    with pytest.raises(ValueError, match="ambiguous"):
        writer.write_trace_record(execution("IB_002", "Model1"))


def test_append_reads_existing_identity(tmp_path):
    writer = TraceFileGenerator("run.trc", directory=str(tmp_path))
    writer.write_trace_record(execution())
    append_writer = TraceFileGenerator("run.trc", mode="append", directory=str(tmp_path))
    with pytest.raises(ValueError, match="Duplicate"):
        append_writer.write_trace_record(execution())


def test_trace_validates_paver_semantics(tmp_path):
    writer = TraceFileGenerator("run.trc", directory=str(tmp_path))
    with pytest.raises(ValueError, match="Direction"):
        writer.write_trace_record(execution(), direction=0)
    with pytest.raises(ValueError, match="TerminationStatus"):
        writer.write_trace_record(execution("IB_002", termination_status="105"))
    with pytest.raises(ValueError, match="ModelStatus"):
        writer.write_trace_record(execution("IB_003", model_status=105))
