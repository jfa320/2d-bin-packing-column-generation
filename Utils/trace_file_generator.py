"""Serialize solver-independent results using PAVER's custom trace definition."""

import math
from pathlib import Path

from utils.execution_result import ColumnGenerationExecutionResult, ExecutionResult


TERMINATION_STATUSES = frozenset({
    "Normal", "TimeLimit", "NodeLimit", "IterationLimit", "OtherLimit",
    "UserInterrupt", "CapabilityProblem", "Error", "Other",
})
TRACE_COLUMNS = (
    "InputFileName", "SolverName", "Direction", "ModelStatus",
    "TerminationStatus", "ObjectiveValue", "SolverTime", "NumberOfIterations",
)
TRACE_HEADER = "* Trace Record Definition\n* " + ",".join(TRACE_COLUMNS) + "\n"


def _identity(case_name, model_name):
    # The official reader strips these suffixes, in this order, before deduplication.
    for suffix in (".gz", ".bz2", ".gms"):
        if case_name.endswith(suffix):
            case_name = case_name[:-len(suffix)]
    return case_name, model_name


class TraceFileGenerator:
    def __init__(self, filename, mode="overwrite", directory="Results"):
        if mode not in {"overwrite", "append"}:
            raise ValueError("Trace mode must be overwrite or append")
        self.path = Path(directory) / filename
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if mode == "append" and self.path.exists() and self.path.stat().st_size:
            self._read_keys()
        else:
            self.path.write_text(TRACE_HEADER, encoding="utf-8")

    @staticmethod
    def _validate(result, direction, iterations):
        if type(direction) is not int or direction != 1:
            raise ValueError("Packing traces require Direction=1 (maximization)")
        for name in (result.case_name, result.model_name):
            # PAVER splits lines at commas; CSV quoting is not supported.
            if (not isinstance(name, str) or not name or name != name.strip()
                    or any(char in name for char in ',\r\n') or name.startswith('*')):
                raise ValueError("Trace names must be nonempty, unquoted single fields")
        if result.model_name == "Model1":
            raise ValueError("Use Model1NoRotation or Model1Rotation, not ambiguous Model1")
        if result.termination_status not in TERMINATION_STATUSES:
            raise ValueError(f"Invalid PAVER TerminationStatus: {result.termination_status!r}")
        if result.model_status is not None and (
                type(result.model_status) is not int or not 1 <= result.model_status <= 19):
            raise ValueError("ModelStatus must be an integer in 1..19 or None")
        for name, value in (("SolverTime", result.total_time_s),
                            ("ObjectiveValue", result.objective_value)):
            if value is None and name == "ObjectiveValue":
                continue
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValueError(f"{name} must be finite")
            if name == "SolverTime" and value < 0:
                raise ValueError("SolverTime must be nonnegative")
        if iterations is not None and (type(iterations) is not int or iterations < 0):
            raise ValueError("NumberOfIterations must be a nonnegative integer or None")

    def _read_keys(self):
        keys = set()
        with self.path.open(encoding="utf-8") as stream:
            if stream.readline() + stream.readline() != TRACE_HEADER:
                raise ValueError("Incompatible trace header; use a new file or overwrite")
            for line in stream:
                fields = line.rstrip('\n').split(',')
                if len(fields) != len(TRACE_COLUMNS):
                    raise ValueError("Malformed existing trace record")
                case, model, direction, status, termination, objective, elapsed, iterations = fields
                result = ExecutionResult(
                    case, model, None if status == "NA" else int(status), termination,
                    None if objective == "NA" else float(objective), float(elapsed),
                )
                self._validate(result, int(direction), None if iterations == "NA" else int(iterations))
                key = _identity(case, model)
                if key in keys:
                    raise ValueError(f"Duplicate PAVER instance/solver: {key}")
                keys.add(key)
        return keys

    def write_trace_record(self, result, *, direction=1):
        iterations = None
        if isinstance(result, ColumnGenerationExecutionResult):
            iterations = result.metrics.cg_iterations
            result = result.execution
        if not isinstance(result, ExecutionResult):
            raise TypeError("Trace writer requires ExecutionResult or ColumnGenerationExecutionResult")
        self._validate(result, direction, iterations)
        key = _identity(result.case_name, result.model_name)
        if key in self._read_keys():
            raise ValueError(f"Duplicate PAVER instance/solver: {key}; use a new trace file")
        fields = (
            result.case_name, result.model_name, direction, result.model_status,
            result.termination_status, result.objective_value, result.total_time_s, iterations,
        )
        serialized = ["NA" if value is None else f"{value:.6f}" if isinstance(value, float)
                      else str(value) for value in fields]
        # Always format time consistently, even when callers supply an integer.
        serialized[6] = f"{result.total_time_s:.6f}"
        with self.path.open("a", encoding="utf-8", newline="") as stream:
            stream.write(",".join(serialized) + "\n")
