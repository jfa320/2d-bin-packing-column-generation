import time
from queue import Queue

import pytest

from models.column_generation import column_generation_solver as cg
from models.column_generation.column_generation_solver import orchestrator
from models.column_generation.orchestrator_services import ProblemNormalizer, SolutionMapper
from objects import Item, Slice
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


@pytest.mark.parametrize(
    "dimensions, expected_layout",
    [
        ((9, 6, 3, 2), [(1, 1, 3, 2, False), (5, 2, 2, 3, True)]),
        ((9, 6, 2, 3), [(1, 1, 3, 2, True), (5, 2, 2, 3, False)]),
        ((6, 9, 3, 2), [(3, 1, 2, 3, True), (1, 5, 3, 2, False)]),
        ((6, 9, 2, 3), [(3, 1, 2, 3, False), (1, 5, 3, 2, True)]),
    ],
    ids=["unchanged", "tall_item", "tall_bin", "tall_bin_and_item"],
)
def test_solution_mapping_preserves_geometry_and_rotation(dimensions, expected_layout):
    problem = ProblemNormalizer().normalize(ConfigData(*dimensions))
    source = [Slice(height=2, width=9, items=[
        Item(width=3, height=2, position_x=1, position_y=1),
        Item(width=2, height=3, position_x=5, position_y=2, rotated=True),
    ])]

    output = SolutionMapper().denormalize(source, problem)
    layout = [
        (*item.get_position(), item.get_width(), item.get_height(), item.get_rotated())
        for slice_ in output for item in slice_.get_items()
    ]
    assert layout == expected_layout
    validate_feasibility(output, dimensions[0], dimensions[1], objective_value=2)
    assert [(*item.get_position(), item.get_width(), item.get_height(), item.get_rotated())
            for item in source[0].get_items()] == [
                (1, 1, 3, 2, False), (5, 2, 2, 3, True)]
    assert output[0].get_width() == dimensions[0]
    # A rotated bin's original vertical extent comes from its normalized width.
    assert output[0].get_height() == (9 if problem.normalized_bin else 2)


def test_solution_mapping_accepts_empty_layout_for_rotation_only_fit():
    problem = ProblemNormalizer().normalize(ConfigData(2, 3, 3, 2))
    assert SolutionMapper().denormalize([], problem) == []


@pytest.mark.parametrize("return_mode", ["objective", "solution", "structured"])
@pytest.mark.parametrize(
    "dimensions, expected",
    [
        ((2, 3, 3, 2), 1),
        ((2, 3, 2, 3), 1),
        ((3, 2, 2, 3), 1),
        ((3, 2, 3, 2), 1),
        ((3, 6, 2, 3), 3),
        ((6, 3, 3, 2), 3),
    ],
    ids=["rotation_only", "both_tall", "tall_item", "unchanged",
         "tall_bin_multiple", "wide_bin_multiple"],
)
def test_orchestrator_public_output_after_normalization(
    monkeypatch, dimensions, expected, return_mode
):
    exported_slices = []
    export_layout = cg.export_final_layout

    def capture_layout(*args):
        exported_slices.extend(args[-1])
        return export_layout(*args)

    monkeypatch.setattr(cg, "export_final_layout", capture_layout)
    result = orchestrator(
        Queue(), None, 10, time.perf_counter(), ConfigData(*dimensions),
        case_name=f"mapping_{'_'.join(map(str, dimensions))}_{return_mode}",
        return_solution=return_mode == "solution",
        return_structured=return_mode == "structured",
        threads=1, random_seed=0,
    )

    if return_mode == "structured":
        assert result.execution.termination_status == "Normal"
        assert result.execution.error_message is None
        assert result.execution.objective_value == expected
        assert result.metrics.lp_value == pytest.approx(expected)
        assert result.metrics.restricted_integer_master == expected
        assert result.diagnostics.lp_convergence_proven
        assert result.diagnostics.cg_stop_reason == "pricing_converged"
    elif return_mode == "solution":
        objective, active_slices = result
        assert objective == expected
        assert active_slices == exported_slices
    else:
        assert result == expected

    validate_feasibility(exported_slices, dimensions[0], dimensions[1], expected)
    for slice_ in exported_slices:
        for item in slice_.get_items():
            original = dimensions[2:]
            assert (item.get_width(), item.get_height()) == (
                original[::-1] if item.get_rotated() else original)
    if expected == 1:
        item = exported_slices[0].get_items()[0]
        assert (*item.get_position(), item.get_width(), item.get_height()) == (
            0, 0, dimensions[0], dimensions[1])
