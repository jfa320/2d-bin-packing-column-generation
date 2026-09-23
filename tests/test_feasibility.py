import time

import pytest

from models.column_generation.column_generation_solver import orchestrator
from objects.ConfigData import ConfigData
from helper_methods import validate_feasibility


FEASIBILITY_CASES = [
    ("case1", (6, 4, 2, 3), 4),
    ("case2", (5, 5, 3, 2), 4),
    ("case6", (6, 6, 3, 2), 6),
    ("case3", (6, 6, 4, 2), 4),
    ("case4", (7, 3, 3, 2), 3),
    ("case5", (6, 3, 3, 2), 3),
    ("case7", (120, 20, 12, 8), 25),
    ("case8", (50, 20, 13, 8), 7),
    ("case9", (40, 25, 10, 6), 16),
    ("case10", (60, 20, 12, 7), 13),
    ("case11", (45, 30, 9, 9), 15),
    ("case12", (70, 25, 14, 8), 15),
    ("case13", (55, 22, 11, 6), 18),
    ("case14", (20, 20, 6, 5), 12),
    ("case15", (40, 30, 10, 7), 16),
    ("case16", (60, 25, 12, 5), 25),
    ("case17", (48, 24, 8, 6), 24),
    ("case18", (70, 28, 14, 7), 20),
    ("case19", (10, 30, 1, 6), 50),
]


@pytest.mark.parametrize(
    "case_name, dimensions, expected", FEASIBILITY_CASES,
    ids=[case[0] for case in FEASIBILITY_CASES],
)
def test_orchestrator_solution_is_feasible(
    orchestrator_context, case_name, dimensions, expected
):
    queue, manual_interruption, execution_time = orchestrator_context
    config_data = ConfigData(*dimensions)
    objective_value, active_slices = orchestrator(
        queue, manual_interruption, execution_time, time.time(), config_data,
        case_name=case_name, return_solution=True,
    )

    assert objective_value == expected
    validate_feasibility(
        active_slices, config_data.get_bin_width(), config_data.get_bin_height(),
        objective_value,
    )


class ItemDummy:
    def __init__(self, x, y, width, height):
        self.x, self.y, self.width, self.height = x, y, width, height

    def get_position_x(self):
        return self.x

    def get_position_y(self):
        return self.y

    def get_width(self):
        return self.width

    def get_height(self):
        return self.height


class SliceDummy:
    def __init__(self, items):
        self.items = items

    def get_items(self):
        return self.items


def test_feasibility_rejects_overlapping_items():
    slices = [SliceDummy([
        ItemDummy(x=0, y=0, width=2, height=2),
        ItemDummy(x=1, y=1, width=2, height=2),
    ])]

    with pytest.raises(AssertionError):
        validate_feasibility(slices, bin_width=5, bin_height=5, objective_value=2)
