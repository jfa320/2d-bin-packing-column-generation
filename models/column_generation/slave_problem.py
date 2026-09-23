"""Pricing problem for column generation.

Construction, solving and solution mapping are intentionally separate.  The
legacy functions at the bottom preserve the original public API.
"""

import cplex

from config import USE_PRACTICAL_CG_ENHANCEMENTS
from objects import Item, Slice
from utils.cplex_helpers import add_constraint_set, add_variables
from utils.paver_constants import PaverConstants
from utils.status_normalizer import map_cplex_mip_status

MODEL_NAME = "Model5SlaveAlternative"
DISABLE_DUPLICATE_CONSTRAINT_CHECK = True
PAVER = PaverConstants


def build_items(variable_names, variable_values, height_item, width_item):
    items = []
    for name, value in zip(variable_names, variable_values):
        if not name.startswith("z_") or value <= 0.5:
            continue
        _, rotation, x, y = name.split("_")
        rotated = rotation == "y"
        height = width_item if rotated else height_item
        width = height_item if rotated else width_item
        item = Item(
            height=height, width=width, rotated=rotated,
            position_x=int(x), position_y=int(y),
        )
        if item not in items:
            items.append(item)
    return items


def build_occupied_positions(variable_names, variable_values, height_item, width_item):
    occupied = set()
    for name, value in zip(variable_names, variable_values):
        if not name.startswith("z_") or value <= 0.5:
            continue
        _, rotation, x, y = name.split("_")
        rotated = rotation == "y"
        height = width_item if rotated else height_item
        width = height_item if rotated else width_item
        for dx in range(width):
            for dy in range(height):
                occupied.add((int(x) + dx, int(y) + dy))
    return list(occupied)


def get_max_y(positions_occupied, height_item, width_item, items):
    del height_item, width_item
    if not positions_occupied:
        return None
    item_pos_y_max = max(items, key=lambda item: item.get_position_y())
    return item_pos_y_max.get_position_y() + item_pos_y_max.get_height()


def rects_overlap(x1, y1, w1, h1, x2, y2, w2, h2):
    return not (
        x1 + w1 <= x2 or x2 + w2 <= x1
        or y1 + h1 <= y2 or y2 + h2 <= y1
    )


class SlaveModelBuilder:
    """Build the binary pricing model from positions and master duals."""

    def __init__(self, disable_duplicate_constraint_check=DISABLE_DUPLICATE_CONSTRAINT_CHECK):
        self.disable_duplicate_constraint_check = disable_duplicate_constraint_check

    def build(self, max_time, xy_x, xy_y, dual_values, width_bin,
              height_item_sin_rotar, width_item_sin_rotar, height_bin,
              slice_height):
        height_item = height_item_sin_rotar
        width_item = width_item_sin_rotar
        valid_x_positions = [
            (a, b) for a, b in xy_x
            if a + width_item <= width_bin and b + height_item <= height_bin
        ]
        valid_y_positions = [
            (a, b) for a, b in xy_y
            if a + height_item <= width_bin and b + width_item <= height_bin
        ]

        occupied_regions = {}
        for a, b in valid_x_positions:
            occupied_regions[(a, b, "x")] = [
                (x, y)
                for x in range(a, a + width_item)
                for y in range(b, b + height_item)
            ]
        for a, b in valid_y_positions:
            occupied_regions[(a, b, "y")] = [
                (x, y)
                for x in range(a, a + height_item)
                for y in range(b, b + width_item)
            ]

        model = cplex.Cplex()
        model.parameters.preprocessing.presolve.set(0)
        model.objective.set_sense(model.objective.sense.maximize)
        model.parameters.timelimit.set(max_time)

        def dual_sum(a, b, rotation):
            return sum(
                dual_values["pi"].get(f"({x},{y})", 0.0)
                for x, y in occupied_regions[(a, b, rotation)]
            )

        non_rotated_names = [f"z_x_{a}_{b}" for a, b in valid_x_positions]
        non_rotated_objective = [
            1.0 - dual_sum(a, b, "x") for a, b in valid_x_positions
        ]
        add_variables(model, non_rotated_names, non_rotated_objective, "B")

        rotated_names = [f"z_y_{a}_{b}" for a, b in valid_y_positions]
        rotated_objective = [
            1.0 - dual_sum(a, b, "y") for a, b in valid_y_positions
        ]
        add_variables(model, rotated_names, rotated_objective, "B")

        y_bases = sorted({
            b for _, b in valid_x_positions + valid_y_positions
        })
        window_names = [f"s_{y_base}" for y_base in y_bases]
        add_variables(model, window_names, [0.0] * len(window_names), "B")

        cover_map = {}
        for (a, b, rotation), cells in occupied_regions.items():
            variable_name = f"z_{rotation}_{a}_{b}"
            for cell in cells:
                cover_map.setdefault(cell, set()).add(variable_name)

        added_constraints = set()
        for (x, y), covering_variables in cover_map.items():
            add_constraint_set(
                model, [1.0] * len(covering_variables), covering_variables,
                1, "L", added_constraints, f"consNoOverlap_{x}_{y}",
                self.disable_duplicate_constraint_check,
            )

        if window_names:
            add_constraint_set(
                model, [1.0] * len(window_names), window_names, 1, "L",
                added_constraints, "consOneSliceWindow",
                self.disable_duplicate_constraint_check,
            )

        for a, b in valid_x_positions:
            self._add_window_constraint(
                model, added_constraints, f"z_x_{a}_{b}", b,
                y_bases, slice_height, f"consSliceWindow_x_{a}_{b}"
            )
        for a, b in valid_y_positions:
            self._add_window_constraint(
                model, added_constraints, f"z_y_{a}_{b}", b,
                y_bases, slice_height, f"consSliceWindow_y_{a}_{b}"
            )
        return model

    def _add_window_constraint(self, model, added_constraints, variable_name,
                               y, y_bases, slice_height, constraint_name):
        windows = [
            f"s_{y_base}" for y_base in y_bases
            if y_base <= y < y_base + slice_height
        ]
        add_constraint_set(
            model, [1.0] + [-1.0] * len(windows),
            [variable_name] + windows, 0.0, "L", added_constraints,
            constraint_name, self.disable_duplicate_constraint_check,
        )


class SlaveSolutionMapper:
    """Reconstruct domain objects from an active CPLEX solution."""

    def map_solution(self, model, bin_width, item_height, item_width, slice_height):
        names = model.variables.get_names()
        values = model.solution.get_values()
        items = build_items(names, values, item_height, item_width)
        active_variables = [
            name for name, value in zip(names, values)
            if value > 0.5 and (name.startswith("z_x_") or name.startswith("z_y_"))
        ]
        if not items:
            return None, [], [], None
        build_occupied_positions(names, values, item_height, item_width)
        slice_ = Slice(
            height=slice_height, width=bin_width, items=items
        )
        return slice_, items, active_variables, (names, values)

    @staticmethod
    def calculate_original_objective(names, values, original_coefficients):
        return sum(
            original_coefficients.get(name, 0.0)
            for name, value in zip(names, values) if value > 0.5
        )


class SlaveSolver:
    """Solve pricing and optionally perform its structural second phase."""

    EPS_SECOND_PHASE = 1e-8

    def __init__(self, solution_mapper=None):
        self.solution_mapper = solution_mapper or SlaveSolutionMapper()

    def solve(self, model, queue, manual_interruption, bin_width, item_height,
              item_width, slice_height, finalization_heuristics=None):
        del manual_interruption
        model.solve()
        if not self._report_status(model, queue):
            return None, None, []

        phase_1_objective = model.solution.get_objective_value()
        names = model.variables.get_names()
        linear_objective = model.objective.get_linear()
        original_coefficients = dict(zip(names, linear_objective))
        phase_1 = self.solution_mapper.map_solution(
            model, bin_width, item_height, item_width, slice_height
        )
        phase_1_slice, phase_1_items, phase_1_active, _ = phase_1
        if phase_1_slice is None:
            return None, phase_1_objective, []

        enhancements = (
            USE_PRACTICAL_CG_ENHANCEMENTS
            if finalization_heuristics is None else finalization_heuristics
        )
        if not enhancements:
            return phase_1_slice, phase_1_objective, phase_1_active

        try:
            model.linear_constraints.add(
                lin_expr=[cplex.SparsePair(ind=names, val=linear_objective)],
                senses=["G"],
                rhs=[phase_1_objective - self.EPS_SECOND_PHASE],
                names=["consMaintainOriginalObjective"],
            )
            model.objective.set_linear([(name, 0.0) for name in names])
            model.objective.set_linear([
                (name, 1.0) for name in names
                if name.startswith("z_x_") or name.startswith("z_y_")
            ])
            model.objective.set_sense(model.objective.sense.maximize)
            model.solve()
            if self._report_status(model, queue):
                phase_2 = self.solution_mapper.map_solution(
                    model, bin_width, item_height, item_width, slice_height
                )
                phase_2_slice, phase_2_items, phase_2_active, raw_solution = phase_2
                if phase_2_slice is not None:
                    phase_2_names, phase_2_values = raw_solution
                    phase_2_objective = self.solution_mapper.calculate_original_objective(
                        phase_2_names, phase_2_values, original_coefficients
                    )
                    if (
                        phase_2_objective >= phase_1_objective - self.EPS_SECOND_PHASE
                        and len(phase_2_items) > len(phase_1_items)
                    ):
                        return phase_2_slice, phase_1_objective, phase_2_active
        except Exception as error:
            queue.put({"phase": "pricing", "error": str(error)})

        return phase_1_slice, phase_1_objective, phase_1_active

    @staticmethod
    def _report_status(model, queue):
        raw_status = model.solution.get_status()
        reported_feasible = model.solution.is_primal_feasible()
        state = map_cplex_mip_status(
            raw_status, has_feasible_solution=reported_feasible
        )
        queue.put({
            "phase": "pricing", "raw_status": raw_status, "state": state
        })
        return state.has_feasible_solution


_MODEL_BUILDER = SlaveModelBuilder()
_SOLVER = SlaveSolver()


def create_slave_model(max_time, xy_x, xy_y, dual_values, width_bin,
                       height_item_sin_rotar, width_item_sin_rotar, height_bin,
                       slice_height):
    return _MODEL_BUILDER.build(
        max_time, xy_x, xy_y, dual_values, width_bin,
        height_item_sin_rotar, width_item_sin_rotar, height_bin, slice_height,
    )


def solve_slave_model(model, queue, manual_interruption, bin_width, item_height,
                      item_width, slice_height, finalization_heuristics=None):
    return _SOLVER.solve(
        model, queue, manual_interruption, bin_width, item_height, item_width,
        slice_height, finalization_heuristics,
    )
