"""Global normal sets and orientation mapping; no solver dependency."""

import itertools

import pytest

from models.quadrant_column_generation import (
    Placement, build_quadrants, generate_global_discretization,
)
from models.quadrant_column_generation import discretization as module


def test_normal_sets_include_normal_borders_but_not_arbitrary_integers():
    grid = generate_global_discretization(12, 8, 3, 2)

    assert grid.I == {0, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12}
    assert grid.J == {0, 2, 3, 4, 5, 6, 7, 8}
    assert (12, 8) not in grid.Px | grid.Py


def test_orientation_sets_filter_the_full_rectangle():
    grid = generate_global_discretization(7, 5, 3, 2)

    assert grid.Px == set(itertools.product({0, 2, 3, 4}, {0, 2, 3}))
    assert grid.Py == set(itertools.product({0, 2, 3, 4, 5}, {0, 2}))
    assert (5, 2) not in grid.Px
    assert (5, 2) in grid.Py
    assert (4, 3) in grid.Px
    assert (4, 3) not in grid.Py


@pytest.mark.parametrize("dimensions", [
    (7, 5, 3, 2), (5, 7, 3, 2), (7, 5, 2, 3), (5, 7, 2, 3),
])
def test_normalization_preserves_input_axes_and_orientation(dimensions):
    L, W, l, w = dimensions
    grid = generate_global_discretization(*dimensions)
    # Independent membership oracle: enumerate integer corners and check
    # representability, instead of transposing the generator's output.
    def normal(value):
        return any((value - a * l) % w == 0 for a in range(value // l + 1))

    assert grid.I == {i for i in range(L + 1) if normal(i)}
    assert grid.J == {j for j in range(W + 1) if normal(j)}
    assert grid.Px == {
        (i, j) for i in range(max(0, L - l + 1))
        for j in range(max(0, W - w + 1)) if normal(i) and normal(j)
    }
    assert grid.Py == {
        (i, j) for i in range(max(0, L - w + 1))
        for j in range(max(0, W - l + 1)) if normal(i) and normal(j)
    }
    assert all(grid.contains_placement(p) for p in grid.placements)
    assert {
        (p.width, p.height) for p in grid.placements if not p.rotated
    } == {(l, w)}
    assert {
        (p.width, p.height) for p in grid.placements if p.rotated
    } == {(w, l)}


@pytest.mark.parametrize("dimensions", [(10, 8, 3, 3), (8, 10, 3, 3)])
def test_squares_keep_both_mathematical_sets_without_duplicate_placements(dimensions):
    grid = generate_global_discretization(*dimensions)

    assert grid.Px == grid.Py
    assert len(grid.Px) == 6
    assert len(grid.placements) == 6
    assert all(not p.rotated for p in grid.placements)
    assert grid.contains_placement(Placement(0, 0, 3, 3, rotated=True))


def test_paper_figure_2_placements():
    grid = generate_global_discretization(39, 19, 5, 3)

    assert grid.contains_placement(Placement(9, 6, 5, 3))
    assert grid.contains_placement(Placement(23, 9, 3, 5, rotated=True))


def test_quadrant_filter_reuses_only_the_global_grid(monkeypatch):
    calls = []
    original = module.generate_positions_xym

    def record(*dimensions):
        calls.append(dimensions)
        return original(*dimensions)

    monkeypatch.setattr(module, "generate_positions_xym", record)
    grid = generate_global_discretization(61, 51, 6, 4)
    quadrants = build_quadrants(61, 51, 6, 4).quadrants

    for quadrant in quadrants:
        placements = grid.placements_in(quadrant)
        assert placements
        assert set(placements) <= set(grid.placements)
        assert all(grid.contains_placement(p) for p in placements)
    assert calls == [(61, 51, 6, 4)]
    q4 = quadrants[3]
    assert q4.x_min not in grid.I  # Do not introduce the fractional local origin.
    assert all(p.x >= 50 and p.y >= 42 for p in grid.placements_in(q4))


def test_coverage_uses_normal_points_and_excludes_top_right_edges():
    grid = generate_global_discretization(7, 5, 3, 2)

    assert grid.covered_points(Placement(2, 0, 3, 2)) == {(2, 0), (3, 0), (4, 0)}
    assert not grid.contains_placement(Placement(1, 0, 3, 2))
    assert not grid.contains_placement(Placement(2, 0, 2, 3))
    with pytest.raises(ValueError, match="global discretization"):
        grid.covered_points(Placement(1, 0, 3, 2))


@pytest.mark.parametrize("dimensions", [(2, 3, 5, 4), (3, 2, 4, 5)])
def test_item_that_does_not_fit_has_empty_placement_sets(dimensions):
    grid = generate_global_discretization(*dimensions)

    assert grid.I == grid.J == {0}
    assert not grid.Px
    assert not grid.Py
    assert grid.placements == ()


@pytest.mark.parametrize("bad", [0, -1, True, 2.5])
@pytest.mark.parametrize("index", range(4))
def test_invalid_dimensions_are_rejected(bad, index):
    dimensions = [60, 50, 6, 4]
    dimensions[index] = bad

    with pytest.raises((TypeError, ValueError)):
        generate_global_discretization(*dimensions)
