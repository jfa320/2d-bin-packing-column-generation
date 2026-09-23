"""Small services used by the column-generation orchestrator."""

import math
import os
from dataclasses import dataclass

from objects import Item, Slice
from utils.bin_visualization import export_bin_solution_to_png
from utils.cplex_helpers import add_constraint


@dataclass(frozen=True)
class NormalizedProblem:
    original_bin_width: int
    original_bin_height: int
    original_item_width: int
    original_item_height: int
    bin_width: int
    bin_height: int
    item_width: int
    item_height: int
    normalized_bin: bool
    normalized_item: bool

    @property
    def slice_height(self):
        return calculate_slice_height(
            self.bin_width, self.bin_height, self.item_width, self.item_height
        )


class ProblemNormalizer:
    """Normalize dimensions to the orientation expected by the position generator."""

    def normalize(self, config_data):
        original = (
            config_data.get_bin_width(), config_data.get_bin_height(),
            config_data.get_item_width(), config_data.get_item_height(),
        )
        bin_width, bin_height, item_width, item_height = original
        normalized_bin = bin_height > bin_width
        normalized_item = item_height > item_width
        if normalized_bin:
            bin_width, bin_height = bin_height, bin_width
        if normalized_item:
            item_width, item_height = item_height, item_width
        return NormalizedProblem(
            original_bin_width=original[0], original_bin_height=original[1],
            original_item_width=original[2], original_item_height=original[3],
            bin_width=bin_width, bin_height=bin_height,
            item_width=item_width, item_height=item_height,
            normalized_bin=normalized_bin, normalized_item=normalized_item,
        )


def calculate_slice_height(bin_width, bin_height, item_width, item_height, percentage=0.05):
    max_bound = math.floor((bin_height * bin_width) / (item_height * item_width))
    target_items = math.ceil(max_bound * percentage)
    normal_items_per_row = math.floor(bin_width / item_width)
    normal_rows = math.ceil(target_items / normal_items_per_row)
    rotated_items_per_row = math.floor(bin_width / item_height)
    rotated_rows = math.ceil(target_items / rotated_items_per_row)
    return min(normal_rows * item_height, rotated_rows * item_width)


def calculate_physical_item_bound(bin_width, bin_height, item_width, item_height):
    return math.floor((bin_width * bin_height) / (item_width * item_height))


class InitialSliceGenerator:
    """Create the initial column pool from feasible item start positions."""

    def generate(self, bin_width, bin_height, item_width, item_height,
                 positions_xy_x, positions_xy_y, max_items):
        slice_height = calculate_slice_height(
            bin_width, bin_height, item_width, item_height
        )

        def generate_by_orientation(positions, width, height, rotated):
            slices = []
            placed_items = 0
            positions_set = set(positions)
            positions_by_row = {}
            for x, y in positions:
                positions_by_row.setdefault(y, []).append(x)
            for y in sorted(positions_by_row):
                if placed_items >= max_items:
                    break
                slice_ = Slice(height=slice_height, width=bin_width)
                occupied = set()
                x = 0
                while x + width <= bin_width:
                    if placed_items >= max_items:
                        break
                    region = {
                        (x + dx, y + dy)
                        for dx in range(width) for dy in range(height)
                    }
                    if region & occupied:
                        x += 1
                        continue
                    if (x, y) in positions_set:
                        slice_.place_item(
                            Item(height=height, width=width, rotated=rotated), x, y
                        )
                        occupied |= region
                        placed_items += 1
                        x += width
                    else:
                        x += 1
                if slice_.get_item_start_points():
                    slices.append(slice_)
                    placed_items = 0
            return slices

        return (
            generate_by_orientation(
                positions_xy_x, item_width, item_height, rotated=False
            )
            + generate_by_orientation(
                positions_xy_y, item_height, item_width, rotated=True
            )
        )

    def generate_greedy_uniform(self, bin_width, bin_height, item_width,
                                item_height, max_items):
        slice_height = calculate_slice_height(
            bin_width, bin_height, item_width, item_height
        )

        def generate_by_orientation(width, height, rotated):
            slices = []
            for y in range(0, bin_height - height + 1, height):
                slice_ = Slice(height=slice_height, width=bin_width)
                placed_items = 0
                for x in range(0, bin_width - width + 1, width):
                    if placed_items >= max_items:
                        break
                    slice_.place_item(
                        Item(height=height, width=width, rotated=rotated), x, y
                    )
                    placed_items += 1
                if slice_.get_item_start_points():
                    slices.append(slice_)
            return slices

        rotated_slices = []
        if item_width != item_height:
            rotated_slices = generate_by_orientation(
                item_height, item_width, rotated=True
            )
        return generate_by_orientation(item_width, item_height, False) + rotated_slices


def build_slice_signature(slice_):
    return tuple(sorted(
        (item.get_position_x(), item.get_position_y(), item.get_rotated())
        for item in slice_.get_items()
    ))


def summarize_slice(slice_):
    return sorted(
        (item.get_position_x(), item.get_position_y(), item.get_rotated())
        for item in slice_.get_items()
    )


class SliceRegistry:
    """Keep the generated-column pool and duplicate signatures together."""

    def __init__(self, slices=()):
        self.slices = list(slices)
        self.signatures = {build_slice_signature(slice_) for slice_ in self.slices}

    def contains(self, slice_):
        return build_slice_signature(slice_) in self.signatures

    def add(self, slice_):
        signature = build_slice_signature(slice_)
        if signature in self.signatures:
            return False
        self.slices.append(slice_)
        self.signatures.add(signature)
        return True


class SlaveCutManager:
    """Apply optional pricing cuts without exposing CPLEX details to the loop."""

    def add_no_good_cut(self, slave_model, active_variables, cut_id):
        if not active_variables:
            return
        add_constraint(
            slave_model, [1.0] * len(active_variables), active_variables,
            len(active_variables) - 1, "L", f"nogood_{cut_id}"
        )

    def add_non_empty_constraint(self, slave_model):
        names = [
            name for name in slave_model.variables.get_names()
            if name.startswith("z_x_") or name.startswith("z_y_")
        ]
        if not names:
            return
        add_constraint(
            slave_model, [1.0] * len(names), names, 1.0, "G",
            f"non_empty_{slave_model.linear_constraints.get_num()}"
        )


class SolutionMapper:
    """Convert normalized slices back to the dimensions supplied by the user."""

    def denormalize(self, slices, normalized_problem):
        if not normalized_problem.normalized_bin and not normalized_problem.normalized_item:
            return slices
        slice_height = calculate_slice_height(
            normalized_problem.original_bin_width,
            normalized_problem.original_bin_height,
            normalized_problem.original_item_width,
            normalized_problem.original_item_height,
        )
        output = []
        for slice_ in slices:
            items = []
            for item in slice_.get_items():
                x, y = item.get_position_x(), item.get_position_y()
                width, height = item.get_width(), item.get_height()
                if normalized_problem.normalized_bin:
                    original_x = normalized_problem.original_bin_width - (y + height)
                    original_y = x
                    original_width, original_height = height, width
                else:
                    original_x, original_y = x, y
                    original_width, original_height = width, height
                items.append(Item(
                    height=original_height, width=original_width,
                    rotated=(item.get_rotated()
                             ^ normalized_problem.normalized_bin
                             ^ normalized_problem.normalized_item),
                    position_x=original_x, position_y=original_y,
                ))
            output.append(Slice(
                height=slice_height,
                width=normalized_problem.original_bin_width,
                items=items,
            ))
        return output


class LayoutExporter:
    def export(self, case_name, bin_width, bin_height, item_width, item_height,
               physical_item_bound, active_slices):
        output_path = os.path.join("Results", f"{case_name}_layout.png")
        export_bin_solution_to_png(
            bin_width, bin_height, item_width, item_height,
            physical_item_bound, active_slices, output_path,
        )
        return output_path


def get_active_slices(slices, active_master_variables):
    active_ids = {
        int(name.split("_")[1])
        for name in active_master_variables if name.startswith("p_")
    }
    return [slice_ for slice_ in slices if slice_.get_id() in active_ids]


_INITIAL_SLICE_GENERATOR = InitialSliceGenerator()
_CUT_MANAGER = SlaveCutManager()
_SOLUTION_MAPPER = SolutionMapper()
_LAYOUT_EXPORTER = LayoutExporter()


def generate_initial_slices(*args, **kwargs):
    return _INITIAL_SLICE_GENERATOR.generate(*args, **kwargs)


def generate_initial_slices_greedy_uniform(*args, **kwargs):
    return _INITIAL_SLICE_GENERATOR.generate_greedy_uniform(*args, **kwargs)


def add_no_good_cut(*args, **kwargs):
    return _CUT_MANAGER.add_no_good_cut(*args, **kwargs)


def add_non_empty_constraint(*args, **kwargs):
    return _CUT_MANAGER.add_non_empty_constraint(*args, **kwargs)


def denormalize_slices_for_output(
    slices, bin_width_original, bin_height_original, item_width_original,
    item_height_original, normalized_bin, normalized_item,
):
    problem = NormalizedProblem(
        original_bin_width=bin_width_original,
        original_bin_height=bin_height_original,
        original_item_width=item_width_original,
        original_item_height=item_height_original,
        bin_width=bin_width_original, bin_height=bin_height_original,
        item_width=item_width_original, item_height=item_height_original,
        normalized_bin=normalized_bin, normalized_item=normalized_item,
    )
    return _SOLUTION_MAPPER.denormalize(slices, problem)


def export_final_layout(*args, **kwargs):
    output_path = _LAYOUT_EXPORTER.export(*args, **kwargs)
    print(f"Final layout exported to: {output_path}")
