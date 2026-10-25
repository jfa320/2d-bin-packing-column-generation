"""Immutable geometric placements and configurations, without slice semantics."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .quadrants import Quadrant


@dataclass(frozen=True, order=True)
class Placement:
    """A global rectangle; width/height are its dimensions AFTER orientation.

    ``rotated`` is relative to the original item dimensions. Its footprint is
    [x, x + width) x [y, y + height), so touching edges do not overlap.
    """

    x: int
    y: int
    width: int
    height: int
    rotated: bool = False

    def __post_init__(self):
        for name in ("x", "y", "width", "height"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError(f"{name} must be an integer")
            if value < 0 or (name in ("width", "height") and value == 0):
                raise ValueError(f"invalid placement {name}: {value}")
        if not isinstance(self.rotated, bool):
            raise TypeError("rotated must be a boolean")

    @property
    def right(self):
        return self.x + self.width

    @property
    def top(self):
        return self.y + self.height

    def overlaps(self, other: Placement) -> bool:
        return (
            self.x < other.right and other.x < self.right
            and self.y < other.top and other.y < self.top
        )


@dataclass(frozen=True)
class QuadrantConfiguration:
    """A feasible geometric packing in one quadrant, including the empty one.

    Membership in a global discretization is checked separately through
    ``GlobalDiscretization.contains_placement``. No local grid is introduced.
    """

    quadrant: Quadrant
    placements: tuple[Placement, ...] = ()

    def __post_init__(self):
        placements = tuple(self.placements)
        if not all(isinstance(p, Placement) for p in placements):
            raise TypeError("configuration entries must be Placement objects")
        if len(set(placements)) != len(placements):
            raise ValueError("configuration contains duplicate placements")
        placements = tuple(sorted(placements))
        for index, placement in enumerate(placements):
            if not self.quadrant.contains_placement(placement):
                raise ValueError("placement is not fully contained in the quadrant")
            if any(placement.overlaps(other) for other in placements[:index]):
                raise ValueError("configuration contains overlapping placements")
        object.__setattr__(self, "placements", placements)

    @property
    def item_count(self):
        return len(self.placements)
