import time

import pytest

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
