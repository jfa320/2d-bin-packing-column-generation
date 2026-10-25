"""Marenco Section 3 quadrants, with exact bounds in global coordinates."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from fractions import Fraction
from typing import TYPE_CHECKING

from .discretization import _validate_dimensions

if TYPE_CHECKING:
    from .configuration import Placement


class ApplicabilityStatus(str, Enum):
    APPLICABLE = "applicable"
    NOT_APPLICABLE = "not_applicable"


@dataclass(frozen=True)
class Quadrant:
    index: int
    x_min: Fraction
    y_min: Fraction
    x_max: Fraction
    y_max: Fraction
    right_closed: bool
    top_closed: bool

    def contains_point(self, x, y) -> bool:
        """Point membership, including the paper's open/closed upper bounds."""
        return (
            self.x_min <= x and self.y_min <= y
            and (x <= self.x_max if self.right_closed else x < self.x_max)
            and (y <= self.y_max if self.top_closed else y < self.y_max)
        )

    def contains_placement(self, placement: Placement) -> bool:
        """Contain the WHOLE half-open footprint, allowing shared edges.

        A footprint may end exactly at an open upper bound because that edge
        is excluded from the footprint itself. No rounding or EPS is applied.
        """
        return (
            self.x_min <= placement.x and self.y_min <= placement.y
            and placement.right <= self.x_max and placement.top <= self.y_max
        )


@dataclass(frozen=True)
class QuadrantBuildResult:
    status: ApplicabilityStatus
    alpha: Fraction
    M: int
    quadrants: tuple[Quadrant, ...] = ()
    reason: str | None = None

    @property
    def applicable(self):
        return self.status == ApplicabilityStatus.APPLICABLE


def build_quadrants(
    bin_width: int, bin_height: int, item_width: int, item_height: int,
    alpha: float | Fraction = 0.8,
) -> QuadrantBuildResult:
    """Build Q1..Q4 or explicitly report a valid but inapplicable instance.

    Float alpha is interpreted as its decimal spelling (0.8 means 4/5).
    Invalid dimensions/alpha raise input errors; failed strict applicability
    conditions return NOT_APPLICABLE, without clipping or changing alpha.
    """
    _validate_dimensions(bin_width, bin_height, item_width, item_height)
    if isinstance(alpha, bool) or not isinstance(alpha, (int, float, Fraction)):
        raise TypeError("alpha must be a number")
    try:
        alpha = Fraction(str(alpha))
    except ValueError as error:
        raise ValueError("alpha must be finite") from error
    if not Fraction(1, 2) <= alpha <= 1:
        raise ValueError("alpha must lie in [0.5, 1]")

    M = max(item_width, item_height)
    x_cut, y_cut = alpha * bin_width, alpha * bin_height
    x_end, y_end = x_cut + M, y_cut + M
    failures = []
    if not x_end < bin_width:
        failures.append(f"alpha * L + M < L is false ({x_end} >= {bin_width})")
    if not y_end < bin_height:
        failures.append(f"alpha * W + M < W is false ({y_end} >= {bin_height})")
    if failures:
        return QuadrantBuildResult(
            ApplicabilityStatus.NOT_APPLICABLE, alpha, M,
            reason="; ".join(failures),
        )

    zero, L, W = Fraction(0), Fraction(bin_width), Fraction(bin_height)
    quadrants = (
        Quadrant(1, zero, zero, x_end, y_end, False, False),
        Quadrant(2, zero, y_cut, x_end, W, False, True),
        Quadrant(3, x_cut, zero, L, y_end, True, False),
        Quadrant(4, x_cut, y_cut, L, W, True, True),
    )
    return QuadrantBuildResult(ApplicabilityStatus.APPLICABLE, alpha, M, quadrants)
