"""Error envelopes shared by legacy model workers."""

from utils.paver_constants import PaverConstants

PAVER = PaverConstants


def handle_solver_error(error, queue, solver_time):
    queue.put({
        "modelStatus": PAVER.LEGACY_MODEL_STATUS_ERROR,
        "solverStatus": PAVER.LEGACY_SOLVER_STATUS_ERROR,
        "objectiveValue": None,
        "solverTime": solver_time,
        "error_message": str(error),
    })
