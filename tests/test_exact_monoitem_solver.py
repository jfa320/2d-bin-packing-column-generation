"""Exact packing regressions and an independent integer-grid oracle."""

from functools import lru_cache
from itertools import product
from queue import Queue
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from models.comparative import exact_monoitem_solver as solver
from models.comparative import Model_7_Exact_Monoitem_Backtracking as adapter
from utils.trace_file_generator import TraceFileGenerator


ZERO_CASES = [(5, 5, 6, 1), (5, 5, 11, 1), (2, 2, 3, 2)]


def _instance(dimensions):
    return dict(
        case_name="zero_packing",
        **dict(zip(("bin_width", "bin_height", "item_width", "item_height"), dimensions)),
    )


@pytest.mark.parametrize("dimensions", ZERO_CASES + [(5, 2, 3, 3), (10, 4, 6, 6)])
@pytest.mark.parametrize("rotation", [False, True])
def test_no_fitting_orientation_has_zero_optimum(dimensions, rotation):
    W, H, w, h = dimensions
    result = solver.solve_exact_monoitem_2dbpp(*dimensions, allow_rotation=rotation)
    assert result == dict(
        bin_width=W, bin_height=H, item_width=w, item_height=h,
        allow_rotation=rotation, capacity=0,
        area_upper_bound=(W * H) // (w * h), placements=[],
    )


@pytest.mark.parametrize("index", range(4))
@pytest.mark.parametrize("invalid", [0, -1, 1.5, "1", None])
def test_invalid_dimensions_remain_errors(index, invalid):
    dimensions = [5, 5, 1, 1]
    dimensions[index] = invalid
    with pytest.raises(ValueError, match="positive integers"):
        solver.solve_exact_monoitem_2dbpp(*dimensions)


@pytest.mark.parametrize("dimensions", [(3, 2, 2, 3), (4, 6, 6, 4)])
def test_item_that_only_fits_rotated_respects_rotation_flag(dimensions):
    assert solver.solve_exact_monoitem_2dbpp(
        *dimensions, allow_rotation=False,
    )["capacity"] == 0
    W, H, w, h = dimensions
    result = solver.solve_exact_monoitem_2dbpp(*dimensions, allow_rotation=True)
    assert result["capacity"] == 1
    assert result["placements"] == [dict(x=0, y=0, width=h, height=w, rotated=True)]
    assert (result["bin_width"], result["bin_height"]) == (W, H)
    assert (result["item_width"], result["item_height"]) == (w, h)


def _enumerated_capacity(W, H, w, h, rotation):
    """Enumerate all integer placements, choosing a rectangle or an empty cell."""
    orientations = {(w, h), (h, w)} if rotation else {(w, h)}
    full = (1 << (W * H)) - 1
    covering = [[] for _ in range(W * H)]
    for width, height in orientations:
        for y in range(H - height + 1):
            for x in range(W - width + 1):
                cells = [j * W + i for j in range(y, y + height)
                         for i in range(x, x + width)]
                mask = sum(1 << cell for cell in cells)
                for cell in cells:
                    covering[cell].append(mask)

    @lru_cache(None)
    def enumerate_packings(unavailable):
        free = full ^ unavailable
        if not free:
            return 0
        first = free & -free
        cell = first.bit_length() - 1
        best = enumerate_packings(unavailable | first)
        for mask in covering[cell]:
            if not unavailable & mask:
                best = max(best, 1 + enumerate_packings(unavailable | mask))
        return best

    return enumerate_packings(0)


def _assert_valid_layout(result, W, H, w, h, rotation):
    assert len(result["placements"]) == result["capacity"]
    occupied = set()
    for rectangle in result["placements"]:
        x, y = rectangle["x"], rectangle["y"]
        width, height = rectangle["width"], rectangle["height"]
        rotated = rectangle["rotated"]
        assert not rotated or rotation
        assert (width, height) == ((h, w) if rotated else (w, h))
        assert 0 <= x and x + width <= W
        assert 0 <= y and y + height <= H
        cells = {(i, j) for i in range(x, x + width) for j in range(y, y + height)}
        assert not occupied & cells
        occupied |= cells


@pytest.mark.parametrize("W,H", product(range(1, 6), repeat=2))
def test_small_instances_match_independent_enumerator(W, H):
    for w, h, rotation in product(range(1, 7), range(1, 7), [False, True]):
        result = solver.solve_exact_monoitem_2dbpp(W, H, w, h, rotation, max_time=1)
        expected = _enumerated_capacity(W, H, w, h, rotation)
        assert result["capacity"] == expected, (W, H, w, h, rotation)
        _assert_valid_layout(result, W, H, w, h, rotation)


def _expire_during_search(monkeypatch):
    monkeypatch.setattr(
        solver, "time", SimpleNamespace(perf_counter=Mock(side_effect=[0.0, 1.0])),
    )


def test_search_timeout_is_not_converted_to_zero(monkeypatch):
    _expire_during_search(monkeypatch)
    with pytest.raises(TimeoutError, match="Time limit"):
        solver.solve_exact_monoitem_2dbpp(5, 5, 3, 2, max_time=0.5)


def test_worker_timeout_has_no_objective(monkeypatch):
    _expire_during_search(monkeypatch)
    queue = Queue()
    adapter._solve_in_process(queue, 0.5, _instance((5, 5, 3, 2)))
    result = queue.get_nowait()
    assert (result.model_status, result.termination_status, result.objective_value) == (
        9, "TimeLimit", None,
    )


@pytest.mark.parametrize("dimensions", ZERO_CASES)
def test_public_zero_optimum_and_trace(dimensions, tmp_path):
    result = adapter.execute_with_time_limit(10, _instance(dimensions))
    assert (result.model_status, result.termination_status, result.objective_value) == (
        1, "Normal", 0.0,
    )
    assert result.error_message is None
    writer = TraceFileGenerator("zero.trc", directory=tmp_path)
    writer.write_trace_record(result)
    record = writer.path.read_text(encoding="utf-8").splitlines()[-1].split(",")
    assert record[3:6] == ["1", "Normal", "0.000000"]


def test_expired_parent_budget_does_not_report_zero_optimum():
    result = adapter.execute_with_time_limit(0, _instance(ZERO_CASES[0]))
    assert (result.model_status, result.termination_status, result.objective_value) == (
        9, "TimeLimit", None,
    )
