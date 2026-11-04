"""One deterministic pricing pass over the exact pricing placement domain."""

import math

from models.column_generation.master_problem import calculate_occupied_positions
from models.column_generation.solution_pool import (
    InvalidPoolSolution, candidate_from_values,
)


class GreedyPricingHeuristic:
    """Cache placement geometry; recompute all scores with each original RMP dual."""

    def __init__(self, geometry, xy_x, xy_y):
        self.geometry = geometry
        cells_by_placement = {}
        for rotation, positions, width, height in (
            ("x", xy_x, geometry.item_width, geometry.item_height),
            ("y", xy_y, geometry.item_height, geometry.item_width),
        ):
            for a, b in positions:
                # Match SlaveModelBuilder's filtering of the supplied XY domain.
                if a + width <= geometry.bin_width and b + height <= geometry.bin_height:
                    cells_by_placement[(a, b, rotation)] = tuple(sorted(
                        calculate_occupied_positions((a, b), width, height)))
        self.cells_by_placement = cells_by_placement

    def score_placement(self, placement, duals):
        """The exact coefficient of z_t_a_b, including missing duals as zero."""
        return 1.0 - sum(
            duals["pi"].get(f"({x},{y})", 0.0)
            for x, y in self.cells_by_placement[placement])

    def find_column(self, duals, known_keys, *, eps=1e-9):
        """Return a validated, new improving candidate, or None for exact fallback.

        This result contains no solver status or bound and cannot certify closure.
        No Item/Slice IDs are allocated for rejected candidates.
        """
        scored = [(self.score_placement(placement, duals), placement)
                  for placement in self.cells_by_placement]
        if any(not math.isfinite(score) for score, _ in scored):
            return None
        scored.sort(key=lambda entry: (-entry[0], entry[1]))
        selected, occupied = [], set()
        min_y = max_y = None
        for score, placement in scored:
            if score <= 0:
                break
            a, b, rotation = placement
            cells = self.cells_by_placement[placement]
            if not occupied.isdisjoint(cells):
                continue
            next_min = b if min_y is None else min(min_y, b)
            next_max = b if max_y is None else max(max_y, b)
            if next_max - next_min >= self.geometry.slice_height:
                continue
            selected.append(f"z_{rotation}_{a}_{b}")
            occupied.update(cells)
            min_y, max_y = next_min, next_max

        if not selected:
            return None
        try:
            candidate = candidate_from_values(
                selected, [1.0] * len(selected), duals, self.geometry)
        except InvalidPoolSolution:
            return None
        if (not candidate.placements or candidate.value <= eps
                or candidate.master_key in known_keys):
            return None
        return candidate
