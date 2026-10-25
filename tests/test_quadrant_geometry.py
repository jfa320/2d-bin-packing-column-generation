"""Section 3 quadrant bounds, applicability and full-rectangle containment."""

from fractions import Fraction

import pytest

from models.quadrant_column_generation import (
    ApplicabilityStatus, Placement, build_quadrants,
)


def test_default_alpha_and_the_four_paper_quadrants():
    result = build_quadrants(60, 50, 6, 4)

    assert result.status == ApplicabilityStatus.APPLICABLE
    assert result.applicable
    assert result.reason is None
    assert result.alpha == Fraction(4, 5)
    assert result.M == 6
    assert [
        (q.index, q.x_min, q.y_min, q.x_max, q.y_max,
         q.right_closed, q.top_closed)
        for q in result.quadrants
    ] == [
        (1, 0, 0, 54, 46, False, False),
        (2, 0, 40, 54, 50, False, True),
        (3, 48, 0, 60, 46, True, False),
        (4, 48, 40, 60, 50, True, True),
    ]


@pytest.mark.parametrize("dimensions, failed_axes", [
    ((30, 60, 6, 4), ("L",)),
    ((60, 30, 6, 4), ("W",)),
    ((30, 30, 6, 4), ("L", "W")),
    ((50, 20, 13, 8), ("L", "W")),  # Existing default case7.
])
def test_failed_strict_conditions_return_explicit_not_applicable(dimensions, failed_axes):
    result = build_quadrants(*dimensions)

    assert result.status == ApplicabilityStatus.NOT_APPLICABLE
    assert not result.applicable
    assert result.quadrants == ()
    assert result.alpha == Fraction(4, 5)
    for axis in failed_axes:
        assert f"alpha * {axis} + M < {axis} is false" in result.reason


def test_exact_arithmetic_rejects_equality_and_accepts_the_next_integer():
    assert not build_quadrants(15, 15, 3, 2).applicable
    assert build_quadrants(16, 16, 3, 2).applicable
    assert build_quadrants(31, 31, 4, 6).M == 6
    assert build_quadrants(31, 31, 4, 6).applicable
    assert not build_quadrants(60, 50, 6, 4, alpha=1).applicable


def test_custom_alpha_changes_only_the_documented_cut():
    result = build_quadrants(20, 18, 4, 3, alpha=Fraction(1, 2))

    assert result.applicable
    assert result.quadrants[0].x_max == 14
    assert result.quadrants[0].y_max == 13
    assert result.quadrants[3].x_min == 10
    assert result.quadrants[3].y_min == 9


def test_fractional_limits_are_neither_floored_nor_ceiled():
    q1, q2, q3, q4 = build_quadrants(61, 51, 6, 4).quadrants

    assert (q1.x_max, q1.y_max) == (Fraction(274, 5), Fraction(234, 5))
    assert q2.y_min == q4.y_min == Fraction(204, 5)
    assert q3.x_min == q4.x_min == Fraction(244, 5)
    assert not q3.contains_placement(Placement(48, 0, 6, 4))
    assert q3.contains_placement(Placement(49, 0, 6, 4))
    assert q1.contains_placement(Placement(48, 0, 6, 4))
    assert not q1.contains_placement(Placement(49, 0, 6, 4))


def test_point_membership_respects_each_open_and_closed_upper_edge():
    q1, q2, q3, q4 = build_quadrants(60, 50, 6, 4).quadrants

    assert q1.contains_point(0, 0)
    assert not q1.contains_point(54, 0)
    assert not q1.contains_point(0, 46)
    assert q2.contains_point(0, 40)
    assert q2.contains_point(0, 50)
    assert not q2.contains_point(54, 40)
    assert not q2.contains_point(0, 39)
    assert q3.contains_point(48, 0)
    assert q3.contains_point(60, 0)
    assert not q3.contains_point(48, 46)
    assert not q3.contains_point(47, 0)
    assert q4.contains_point(60, 50)
    assert not q4.contains_point(61, 50)
    assert not q4.contains_point(60, 51)


@pytest.mark.parametrize("index, placement, expected", [
    (0, Placement(48, 42, 6, 4), True),  # Ends at both open upper bounds.
    (0, Placement(50, 40, 4, 6, rotated=True), True),
    (0, Placement(50, 40, 6, 4), False),  # Same start, different orientation.
    (0, Placement(48, 44, 6, 4), False),
    (1, Placement(48, 46, 6, 4), True),
    (1, Placement(48, 38, 6, 4), False),
    (1, Placement(50, 44, 6, 4), False),
    (2, Placement(54, 42, 6, 4), True),
    (2, Placement(46, 42, 6, 4), False),
    (2, Placement(54, 44, 6, 4), False),
    (3, Placement(54, 46, 6, 4), True),
    (3, Placement(56, 44, 4, 6, rotated=True), True),
    (3, Placement(56, 44, 6, 4), False),
    (3, Placement(54, 48, 6, 4), False),
])
def test_full_placement_containment_near_each_frontier(index, placement, expected):
    quadrant = build_quadrants(60, 50, 6, 4).quadrants[index]

    assert quadrant.contains_placement(placement) is expected


def test_start_inside_is_insufficient_when_rectangle_protrudes():
    q1 = build_quadrants(60, 50, 6, 4).quadrants[0]
    placement = Placement(50, 44, 6, 4)

    assert q1.contains_point(placement.x, placement.y)
    assert not q1.contains_placement(placement)


def test_overlapping_quadrants_can_share_a_whole_placement():
    quadrants = build_quadrants(60, 50, 6, 4).quadrants
    common_normal = Placement(48, 40, 6, 4)
    common_rotated = Placement(48, 40, 4, 6, rotated=True)

    assert all(q.contains_point(50, 42) for q in quadrants)
    assert all(q.contains_placement(common_normal) for q in quadrants)
    assert all(q.contains_placement(common_rotated) for q in quadrants)
    # Outside the intersection of all four, it can still belong to a pair.
    assert [q.index for q in quadrants if q.contains_placement(
        Placement(0, 40, 6, 4)
    )] == [1, 2]
    assert [q.index for q in quadrants if q.contains_placement(
        Placement(48, 0, 6, 4)
    )] == [1, 3]


@pytest.mark.parametrize("alpha", [0.49, 1.01, float("inf"), float("nan")])
def test_invalid_alpha_is_an_input_error(alpha):
    with pytest.raises(ValueError, match="alpha"):
        build_quadrants(60, 50, 6, 4, alpha=alpha)


@pytest.mark.parametrize("alpha", [True, "0.8", None])
def test_non_numeric_alpha_is_rejected(alpha):
    with pytest.raises(TypeError, match="alpha"):
        build_quadrants(60, 50, 6, 4, alpha=alpha)


@pytest.mark.parametrize("dimensions", [(0, 50, 6, 4), (60, -1, 6, 4),
                                         (60, 50, True, 4), (60, 50, 6, 4.5)])
def test_invalid_dimensions_are_distinct_from_inapplicability(dimensions):
    with pytest.raises((TypeError, ValueError)):
        build_quadrants(*dimensions)
