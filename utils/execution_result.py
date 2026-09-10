"""Solver-independent results shared by all execution entry points."""

from dataclasses import dataclass
from typing import Optional


@dataclass
class ExecutionResult:
    case_name: str
    model_name: str
    model_status: Optional[int]
    termination_status: str
    objective_value: Optional[float]
    total_time_s: float
    raw_cplex_status: Optional[int] = None
    error_message: Optional[str] = None


@dataclass
class ColumnGenerationMetrics:
    lp_value: Optional[float] = None
    restricted_integer_master: Optional[float] = None
    cg_iterations: int = 0
    generated_columns: int = 0
    cg_time_s: float = 0.0
    integer_master_time_s: float = 0.0


@dataclass
class ColumnGenerationExecutionResult:
    execution: ExecutionResult
    metrics: ColumnGenerationMetrics
