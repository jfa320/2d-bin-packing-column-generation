from types import SimpleNamespace

import main
from utils.execution_result import (
    ColumnGenerationExecutionResult,
    ColumnGenerationMetrics,
    ExecutionResult,
)


def test_main_prints_final_objective_values(monkeypatch, tmp_path, capsys):
    case_name = "case1"
    instance = {
        "case_name": case_name,
        "bin_width": 6,
        "bin_height": 4,
        "item_width": 2,
        "item_height": 3,
        "optimum": 4,
    }

    def model(name, result):
        return SimpleNamespace(
            MODEL_NAME=name,
            execute_with_time_limit=lambda max_time, instance: result,
        )

    models = [
        model("Model5Orchestrator", ColumnGenerationExecutionResult(
            ExecutionResult(case_name, "Model5Orchestrator", 8, "Normal", 4.0, 0.1),
            ColumnGenerationMetrics(),
        )),
        model("Model1NoRotation", ExecutionResult(
            case_name, "Model1NoRotation", 8, "Normal", 3.5, 0.1,
        )),
        model("Model1Rotation", ExecutionResult(
            case_name, "Model1Rotation", 9, "TimeLimit", None, 0.1,
        )),
    ]

    monkeypatch.setattr(main, "MODELS", models)
    monkeypatch.setattr(main, "get_instance", lambda name: instance)
    monkeypatch.chdir(tmp_path)

    main.main([
        "--cases", case_name, "--time", "30", "--no-paver",
        "--output", "summary.trc",
    ])

    output = capsys.readouterr().out
    assert "Final objective values:" in output
    assert "case1 (expected optimum=4):" in output
    assert "  Model5Orchestrator: 4 (time=0.100 s)" in output
    assert "  Model1NoRotation: 3.5 (time=0.100 s)" in output
    assert "  Model1Rotation: N/A (time=0.100 s)" in output
