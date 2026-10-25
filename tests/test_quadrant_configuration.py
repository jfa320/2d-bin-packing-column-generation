"""Basic configuration invariants, independent from CPLEX or column pools."""

from dataclasses import FrozenInstanceError

import pytest

from models.quadrant_column_generation import (
    Placement, QuadrantConfiguration, build_quadrants,
)


def test_placement_dimensions_are_already_oriented_and_immutable():
    placement = Placement(48, 40, 4, 6, rotated=True)

    assert (placement.right, placement.top) == (52, 46)
    with pytest.raises(FrozenInstanceError):
        placement.x = 0


def test_touching_edges_are_allowed_but_positive_area_overlap_is_not():
    placement = Placement(0, 0, 6, 4)

    assert not placement.overlaps(Placement(6, 0, 6, 4))
    assert not placement.overlaps(Placement(0, 4, 6, 4))
    assert placement.overlaps(Placement(5, 3, 6, 4))


def test_empty_configuration_and_order_independent_identity():
    q1 = build_quadrants(60, 50, 6, 4).quadrants[0]
    first, second = Placement(0, 0, 6, 4), Placement(6, 0, 4, 6, rotated=True)

    assert QuadrantConfiguration(q1).item_count == 0
    configuration = QuadrantConfiguration(q1, [second, first])
    assert configuration.item_count == 2
    assert configuration.placements == (first, second)
    assert configuration == QuadrantConfiguration(q1, (first, second))
    assert hash(configuration) == hash(QuadrantConfiguration(q1, (second, first)))


def test_identical_geometry_in_different_quadrants_is_distinct():
    q1, q2, _, _ = build_quadrants(60, 50, 6, 4).quadrants
    placement = Placement(48, 40, 6, 4)

    assert QuadrantConfiguration(q1, (placement,)) != QuadrantConfiguration(q2, (placement,))
    assert QuadrantConfiguration(q1) != QuadrantConfiguration(q2)


@pytest.mark.parametrize("placements, message", [
    ((Placement(0, 0, 6, 4), Placement(4, 0, 6, 4)), "overlapping"),
    ((Placement(0, 0, 6, 4), Placement(0, 0, 6, 4)), "duplicate"),
    ((Placement(50, 44, 6, 4),), "fully contained"),
])
def test_invalid_configurations_are_rejected(placements, message):
    q1 = build_quadrants(60, 50, 6, 4).quadrants[0]

    with pytest.raises(ValueError, match=message):
        QuadrantConfiguration(q1, placements)


@pytest.mark.parametrize("args", [(-1, 0, 6, 4), (0, -1, 6, 4),
                                 (0, 0, 0, 4), (0, 0, 6, -1)])
def test_invalid_placement_geometry_is_rejected(args):
    with pytest.raises(ValueError):
        Placement(*args)


@pytest.mark.parametrize("args", [(True, 0, 6, 4), (0, 0.5, 6, 4),
                                 (0, 0, 6, 4, 1)])
def test_invalid_placement_types_are_rejected(args):
    with pytest.raises(TypeError):
        Placement(*args)


def test_configuration_rejects_non_placement_entries():
    q1 = build_quadrants(60, 50, 6, 4).quadrants[0]

    with pytest.raises(TypeError, match="Placement"):
        QuadrantConfiguration(q1, ((0, 0, 6, 4),))
