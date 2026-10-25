"""Geometry for Marenco's quadrant decomposition, in global pallet coordinates.

This package does not construct optimization models or run column generation.
"""

from .configuration import Placement, QuadrantConfiguration
from .discretization import GlobalDiscretization, generate_global_discretization
from .quadrants import (
    ApplicabilityStatus,
    Quadrant,
    QuadrantBuildResult,
    build_quadrants,
)

__all__ = [
    "ApplicabilityStatus", "GlobalDiscretization", "Placement", "Quadrant",
    "QuadrantBuildResult", "QuadrantConfiguration", "build_quadrants",
    "generate_global_discretization",
]
