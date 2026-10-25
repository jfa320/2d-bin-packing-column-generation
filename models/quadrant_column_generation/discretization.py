"""Beasley normal sets on the GLOBAL pallet (Marenco, Section 2).

I and J retain all normal coordinates, including pallet borders when normal.
Px and Py are the feasible lower-left corners in the original orientation and
its ninety-degree rotation. For square items Px == Py; placements are emitted
only once, with rotated=False.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from models.common.position_generator import generate_positions_xym
from .configuration import Placement

if TYPE_CHECKING:
    from .quadrants import Quadrant


def _validate_dimensions(bin_width, bin_height, item_width, item_height):
    for name, value in (
        ("bin_width", bin_width), ("bin_height", bin_height),
        ("item_width", item_width), ("item_height", item_height),
    ):
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError(f"{name} must be an integer")
        if value <= 0:
            raise ValueError(f"{name} must be positive")


def _normal_coordinates(limit, item_width, item_height):
    return frozenset(
        a * item_width + b * item_height
        for a in range(limit // item_width + 1)
        for b in range((limit - a * item_width) // item_height + 1)
    )


@dataclass(frozen=True)
class GlobalDiscretization:
    bin_width: int
    bin_height: int
    item_width: int
    item_height: int
    I: frozenset[int]
    J: frozenset[int]
    Px: frozenset[tuple[int, int]]
    Py: frozenset[tuple[int, int]]

    @property
    def placements(self) -> tuple[Placement, ...]:
        normal = tuple(
            Placement(x, y, self.item_width, self.item_height)
            for x, y in sorted(self.Px)
        )
        if self.item_width == self.item_height:
            return normal
        return normal + tuple(
            Placement(x, y, self.item_height, self.item_width, rotated=True)
            for x, y in sorted(self.Py)
        )

    def contains_placement(self, placement: Placement) -> bool:
        width, height = (
            (self.item_height, self.item_width) if placement.rotated
            else (self.item_width, self.item_height)
        )
        positions = self.Py if placement.rotated else self.Px
        return (
            (placement.width, placement.height) == (width, height)
            and (placement.x, placement.y) in positions
        )

    def placements_in(self, quadrant: Quadrant) -> tuple[Placement, ...]:
        """Filter global placements; never discretize or translate a quadrant."""
        return tuple(p for p in self.placements if quadrant.contains_placement(p))

    def covered_points(self, placement: Placement) -> frozenset[tuple[int, int]]:
        """Normal points covered by a valid placement, using half-open edges."""
        if not self.contains_placement(placement):
            raise ValueError("placement does not belong to the global discretization")
        return frozenset(
            (i, j) for i in self.I for j in self.J
            if placement.x <= i < placement.right
            and placement.y <= j < placement.top
        )


def generate_global_discretization(
    bin_width: int, bin_height: int, item_width: int, item_height: int,
) -> GlobalDiscretization:
    """Reuse the existing generator, then restore the original axes/orientation.

    Transposing axes preserves the normal sets and their origin. This is not
    a physical rotation/translation of layouts, as used for slice output.
    """
    _validate_dimensions(bin_width, bin_height, item_width, item_height)
    swap_bin = bin_height > bin_width
    swap_item = item_height > item_width
    normal, rotated = generate_positions_xym(
        max(bin_width, bin_height), min(bin_width, bin_height),
        max(item_width, item_height), min(item_width, item_height),
    )
    if swap_bin:
        normal = {(y, x) for x, y in normal}
        rotated = {(y, x) for x, y in rotated}
    if item_width == item_height:
        rotated = normal
    elif swap_bin ^ swap_item:
        normal, rotated = rotated, normal
    return GlobalDiscretization(
        bin_width, bin_height, item_width, item_height,
        _normal_coordinates(bin_width, item_width, item_height),
        _normal_coordinates(bin_height, item_width, item_height),
        frozenset(normal), frozenset(rotated),
    )
