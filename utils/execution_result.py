"""Solver-independent results shared by all execution entry points."""

from dataclasses import dataclass, field
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
    master_lp_time_s: float = 0.0
    pricing_time_s: float = 0.0
    master_build_time_s: float = 0.0
    master_solve_time_s: float = 0.0
    pricing_build_time_s: float = 0.0
    pricing_solve_time_s: float = 0.0


@dataclass
class SolverPhaseStatus:
    """Last completed solve of a phase; None means no status was reported."""

    model_status: Optional[int] = None
    termination_status: Optional[str] = None
    raw_cplex_status: Optional[int] = None


@dataclass
class ColumnGenerationIteration:
    """One master/pricing attempt, including its auxiliary pricing work."""

    iteration: int
    completed: bool = False
    pool_before: int = 0
    pool_after: int = 0
    generated_columns: int = 0
    lp_value: Optional[float] = None
    pricing_objective: Optional[float] = None
    pricing_best_bound: Optional[float] = None
    master_lp_time_s: float = 0.0
    pricing_time_s: float = 0.0
    master_build_time_s: float = 0.0
    master_solve_time_s: float = 0.0
    pricing_build_time_s: float = 0.0
    pricing_solve_time_s: float = 0.0
    iteration_time_s: float = 0.0
    lp_status: SolverPhaseStatus = field(default_factory=SolverPhaseStatus)
    pricing_status: SolverPhaseStatus = field(default_factory=SolverPhaseStatus)
    pricing_phase2_status: SolverPhaseStatus = field(default_factory=SolverPhaseStatus)
    auxiliary_pricing_status: SolverPhaseStatus = field(default_factory=SolverPhaseStatus)
    auxiliary_pricing_phase2_status: SolverPhaseStatus = field(default_factory=SolverPhaseStatus)
    stop_reason: Optional[str] = None
    pricing_calls: int = 0
    pricing_phase2_calls: int = 0
    snapshot_time_s: Optional[float] = field(default=None, repr=False, compare=False)


@dataclass
class ColumnGenerationDiagnostics:
    cg_stop_reason: Optional[str] = None
    lp_convergence_proven: bool = False
    convergence_basis: Optional[str] = None
    interrupted_phase: Optional[str] = None
    lp_status: SolverPhaseStatus = field(default_factory=SolverPhaseStatus)
    pricing_status: SolverPhaseStatus = field(default_factory=SolverPhaseStatus)
    pricing_phase2_status: SolverPhaseStatus = field(default_factory=SolverPhaseStatus)
    auxiliary_pricing_status: SolverPhaseStatus = field(default_factory=SolverPhaseStatus)
    auxiliary_pricing_phase2_status: SolverPhaseStatus = field(default_factory=SolverPhaseStatus)
    integer_master_status: SolverPhaseStatus = field(default_factory=SolverPhaseStatus)
    pricing_objective: Optional[float] = None
    pricing_best_bound: Optional[float] = None
    # Monotonic clock and active phase let the parent account for an interrupted
    # build/solve even when the worker cannot send a final snapshot.
    active_phase: Optional[str] = None
    snapshot_time_s: Optional[float] = field(default=None, repr=False, compare=False)
    active_component: Optional[str] = None


@dataclass
class ColumnGenerationExecutionResult:
    execution: ExecutionResult
    metrics: ColumnGenerationMetrics
    diagnostics: ColumnGenerationDiagnostics = field(default_factory=ColumnGenerationDiagnostics)
    iterations: list[ColumnGenerationIteration] = field(default_factory=list)
    current_iteration: Optional[ColumnGenerationIteration] = None
