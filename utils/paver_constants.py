"""Canonical values used by the current PAVER trace/result pipeline."""


class PaverConstants:
    """PAVER values shared by result producers and trace serialization."""

    # Trace direction. The packing problem maximizes the objective.
    DIRECTION_MAXIMIZATION = 1

    # ModelStatus values emitted by this project.
    MODEL_STATUS_OPTIMAL = 1
    MODEL_STATUS_INFEASIBLE = 4
    MODEL_STATUS_INTERMEDIATE_INFEASIBLE = 6
    MODEL_STATUS_LP_FEASIBLE = 7
    MODEL_STATUS_FEASIBLE = 8
    MODEL_STATUS_NO_SOLUTION = 9
    MODEL_STATUS_NO_SOLUTION_RETURNED = 10
    MODEL_STATUS_SOLUTION_UNBOUNDED = 12
    MODEL_STATUS_ERROR = 13
    MODEL_STATUS_LOCALLY_OPTIMAL = 18
    MODEL_STATUS_MIN = 1
    MODEL_STATUS_MAX = 19

    # Values kept for the legacy reference-model message envelope.
    LEGACY_MODEL_STATUS_ERROR = "14"
    LEGACY_SOLVER_STATUS_ERROR = "10"

    # TerminationStatus values accepted by the trace definition.
    TERMINATION_NORMAL = "Normal"
    TERMINATION_TIME_LIMIT = "TimeLimit"
    TERMINATION_NODE_LIMIT = "NodeLimit"
    TERMINATION_ITERATION_LIMIT = "IterationLimit"
    TERMINATION_OTHER_LIMIT = "OtherLimit"
    TERMINATION_USER_INTERRUPT = "UserInterrupt"
    TERMINATION_CAPABILITY_PROBLEM = "CapabilityProblem"
    TERMINATION_ERROR = "Error"
    TERMINATION_OTHER = "Other"

    TERMINATION_STATUSES = frozenset({
        TERMINATION_NORMAL,
        TERMINATION_TIME_LIMIT,
        TERMINATION_NODE_LIMIT,
        TERMINATION_ITERATION_LIMIT,
        TERMINATION_OTHER_LIMIT,
        TERMINATION_USER_INTERRUPT,
        TERMINATION_CAPABILITY_PROBLEM,
        TERMINATION_ERROR,
        TERMINATION_OTHER,
    })

    TRACE_COLUMNS = (
        "InputFileName",
        "SolverName",
        "Direction",
        "ModelStatus",
        "TerminationStatus",
        "ObjectiveValue",
        "SolverTime",
        "NumberOfIterations",
    )
