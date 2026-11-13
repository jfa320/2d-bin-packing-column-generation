"""Bounded geometric enrichment of the homogeneous initial column pool."""

from dataclasses import dataclass

import config
from models.column_generation.solution_pool import (
    candidate_from_values, candidate_to_slice, slice_master_key,
)


@dataclass(frozen=True)
class InitialSliceOptions:
    strategy: str = "homogeneous"
    max_extra_columns: int = 24

    def __post_init__(self):
        if self.strategy not in ("homogeneous", "mixed"):
            raise ValueError("initialization must be 'homogeneous' or 'mixed'")
        if (isinstance(self.max_extra_columns, bool)
                or not isinstance(self.max_extra_columns, int)
                or self.max_extra_columns < 0):
            raise ValueError("initial_mixed_max_columns must be an integer >= 0")

    def as_kwargs(self):
        return {"initialization": self.strategy,
                "initial_mixed_max_columns": self.max_extra_columns}


def resolve_initialization(initialization=None, initial_mixed_max_columns=None):
    """Resolve defaults in the parent before spawning the solver process."""
    return InitialSliceOptions(
        config.INITIALIZATION_STRATEGY if initialization is None else initialization,
        config.INITIAL_MIXED_MAX_COLUMNS if initial_mixed_max_columns is None
        else initial_mixed_max_columns,
    )


def generate_mixed_slices(base_slices, geometry, xy_x, xy_y, options):
    """Return only new mixed rows, without solving or enumerating all placements.

    At most four admissible heights, three compositions and two block orders
    are tried. All items in a candidate share one start y; the taller items may
    protrude above the nominal slice window, as in exact pricing. Validation
    and master-visible deduplication happen before allocating domain IDs.
    """
    if options.strategy != "mixed" or options.max_extra_columns == 0:
        return []
    width, height = geometry.item_width, geometry.item_height
    if width == height:
        return []
    max_normal = (geometry.bin_width - height) // width
    if max_normal < 1:
        return []

    normal_positions, rotated_positions = set(xy_x), set(xy_y)
    rows = sorted({y for _, y in normal_positions}
                  & {y for _, y in rotated_positions})
    if not rows:
        return []
    # Evenly spaced indices include both endpoints; small sets keep all rows.
    rows = [rows[index] for index in sorted({
        part * (len(rows) - 1) // 3 for part in range(4)
    })]
    counts = list(dict.fromkeys((max_normal, max(1, max_normal - 1),
                                (max_normal + 1) // 2)))
    known = {slice_master_key(slice_) for slice_ in base_slices}
    extras = []
    for y in rows:
        if y < 0 or y + max(width, height) > geometry.bin_height:
            continue
        for normal_count in counts:
            rotated_count = (geometry.bin_width - normal_count * width) // height
            if rotated_count < 1:
                continue
            for rotated_first in (False, True):
                groups = [("x", normal_count, width, normal_positions),
                          ("y", rotated_count, height, rotated_positions)]
                if rotated_first:
                    groups.reverse()
                names, x = [], 0
                for rotation, count, item_width, positions in groups:
                    for _ in range(count):
                        if (x, y) not in positions:
                            break
                        names.append(f"z_{rotation}_{x}_{y}")
                        x += item_width
                    else:
                        continue
                    break
                if len(names) != normal_count + rotated_count:
                    continue
                candidate = candidate_from_values(
                    names, [1.0] * len(names), {"pi": {}}, geometry)
                if candidate.master_key in known:
                    continue
                known.add(candidate.master_key)
                extras.append(candidate_to_slice(candidate, geometry))
                if len(extras) >= options.max_extra_columns:
                    return extras
    return extras
