"""Pricing problem for column generation.

Construction, solving and solution mapping are intentionally separate.  The
legacy functions at the bottom preserve the original public API.
"""

import cplex
import math
from contextlib import contextmanager
from numbers import Real
from utils.cg_instrumentation import timed_component

from models.column_generation.pricing_options import resolve_pricing_heuristics
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


class PricingStateError(RuntimeError):
    """The persistent pricing cannot safely be solved again."""


@contextmanager
def temporary_pricing_changes(model, progress=None):
    """Restore the objective and remove appended rows, including on failure.

    Auxiliary searches may only append rows and change the linear objective.
    Nested scopes preserve the exclusions of their enclosing search.
    """
    variables = model.variables.get_num()
    rows = model.linear_constraints.get_num()
    coefficients = model.objective.get_linear()
    sense = model.objective.get_sense()
    try:
        yield model
    finally:
        with timed_component(progress, "pricing_build"):
            try:
                current_rows = model.linear_constraints.get_num()
                if model.variables.get_num() != variables or current_rows < rows:
                    raise ValueError("Auxiliary search changed the base pricing structure")
                if current_rows > rows:
                    model.linear_constraints.delete(rows, current_rows - 1)
                model.objective.set_linear(list(enumerate(coefficients)))
                model.objective.set_sense(sense)
                if (model.linear_constraints.get_num() != rows
                        or model.objective.get_linear() != coefficients
                        or model.objective.get_sense() != sense):
                    raise ValueError("Temporary pricing changes were not restored")
            except Exception as error:
                raise PricingStateError(f"Cannot restore persistent pricing: {error}") from error


class IncrementalPricingModel:
    """Build one pricing instance; update it or fail without rebuilding."""

    def __init__(self, max_time, xy_x, xy_y, width_bin, height_item,
                 width_item, height_bin, slice_height, *, model_factory=None):
        self._geometry = (
            max_time, tuple(xy_x), tuple(xy_y), width_bin, height_item,
            width_item, height_bin, slice_height,
        )
        self._model_factory = model_factory or create_slave_model
        self.model = None
        self._cells_by_variable = ()
        self._shape = None
        self.build_count = 0
        self._closed = False

    def _build(self, dual_values):
        (max_time, xy_x, xy_y, width_bin, height_item,
         width_item, height_bin, slice_height) = self._geometry
        model = self._model_factory(
            max_time, xy_x, xy_y, dual_values, width_bin,
            height_item, width_item, height_bin, slice_height,
        )
        try:
            # Reuse the matrix, but start each MIP search from scratch. Carrying
            # incumbents between dual vectors changes which tied columns CPLEX
            # returns and can worsen the final restricted integer solution.
            model.parameters.advance.set(0)
            cells_by_variable = []
            for name in model.variables.get_names():
                if name.startswith("s_"):
                    cells_by_variable.append(None)
                    continue
                prefix, rotation, x, y = name.split("_")
                if prefix != "z" or rotation not in {"x", "y"}:
                    raise ValueError(f"Unexpected pricing variable: {name}")
                width, height = ((width_item, height_item) if rotation == "x"
                                 else (height_item, width_item))
                cells_by_variable.append(tuple(
                    f"({a},{b})"
                    for a in range(int(x), int(x) + width)
                    for b in range(int(y), int(y) + height)
                ))
            self._shape = (model.variables.get_num(), model.linear_constraints.get_num())
        except Exception:
            model.end()
            raise
        self.model = model
        self._cells_by_variable = tuple(cells_by_variable)
        self.build_count += 1
        return model

    def prepare(self, dual_values):
        if self._closed:
            raise PricingStateError("Pricing session is closed; rebuilding is disabled")
        if self.model is None:
            try:
                return self._build(dual_values)
            except Exception:
                self.close()
                raise
        try:
            shape = (self.model.variables.get_num(), self.model.linear_constraints.get_num())
            if shape != self._shape:
                raise ValueError("Base pricing structure was modified")
            pi = dual_values["pi"]
            coefficients = [
                (index, 0.0 if cells is None else
                 1.0 - sum(pi.get(cell, 0.0) for cell in cells))
                for index, cells in enumerate(self._cells_by_variable)
            ]
            self.model.objective.set_linear(coefficients)
            self.model.objective.set_sense(self.model.objective.sense.maximize)
            # No solutions from another dual vector or an auxiliary objective.
            self.model.solution.pool.delete()
        except Exception as error:
            # A partially updated model must never be solved or rebuilt silently.
            self.close()
            raise PricingStateError(f"Incremental pricing update failed: {error}") from error
        return self.model

    def close(self):
        self._closed = True
        model, self.model = self.model, None
        self._cells_by_variable = ()
        self._shape = None
        if model is not None:
            model.end()


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
              item_width, slice_height, *,
              use_pricing_second_phase=None):
        del manual_interruption
        heuristics = resolve_pricing_heuristics(
            use_pricing_second_phase=use_pricing_second_phase)
        with timed_component(queue, "pricing_solve", pricing_stage="primary"):
            model.solve()
        if not self._report_status(model, queue):
            return None, None, []

        phase_1_objective = model.solution.get_objective_value()
        phase_1 = self.solution_mapper.map_solution(
            model, bin_width, item_height, item_width, slice_height
        )
        phase_1_slice, _, phase_1_active, _ = phase_1
        if phase_1_slice is None:
            return None, phase_1_objective, []

        primary = phase_1_slice, phase_1_objective, phase_1_active
        if not heuristics.second_phase:
            return primary
        return self.refine(model, queue, bin_width, item_height, item_width,
                           slice_height, primary)

    def refine(self, model, queue, bin_width, item_height, item_width, slice_height,
               primary, remaining_time=None):
        """Run phase two after the caller has saved the primary solution pool."""
        phase_1_slice, phase_1_objective, _ = primary
        if phase_1_slice is None:
            return primary
        if remaining_time is not None and remaining_time() <= 0:
            return primary
        names = model.variables.get_names()
        linear_objective = model.objective.get_linear()
        original_coefficients = dict(zip(names, linear_objective))

        phase_2_reported = False
        try:
            with temporary_pricing_changes(model, queue):
                with timed_component(queue, "pricing_build"):
                    model.linear_constraints.add(
                        lin_expr=[cplex.SparsePair(ind=names, val=linear_objective)],
                        senses=["G"],
                        rhs=[phase_1_objective - self.EPS_SECOND_PHASE],
                        names=["consMaintainOriginalObjective"],
                    )
                    model.objective.set_linear([
                        (name, float(name.startswith(("z_x_", "z_y_")))) for name in names
                    ])
                    model.objective.set_sense(model.objective.sense.maximize)
                    model.solution.pool.delete()
                    if remaining_time is not None:
                        model.parameters.timelimit.set(max(0.0, remaining_time()))
                with timed_component(queue, "pricing_solve", pricing_stage="phase2"):
                    model.solve()
                phase_2_feasible = self._report_status(model, queue, pricing_stage="phase2")
                phase_2_reported = True
                if phase_2_feasible:
                    phase_2 = self.solution_mapper.map_solution(
                        model, bin_width, item_height, item_width, slice_height
                    )
                    phase_2_slice, phase_2_items, phase_2_active, raw_solution = phase_2
                    if phase_2_slice is not None:
                        phase_2_names, phase_2_values = raw_solution
                        phase_2_objective = self.solution_mapper.calculate_original_objective(
                            phase_2_names, phase_2_values, original_coefficients
                        )
                        if (phase_2_objective >= phase_1_objective - self.EPS_SECOND_PHASE
                                and (phase_1_objective <= 1e-9 or phase_2_objective > 1e-9)
                                and len(phase_2_items) > len(phase_1_slice.get_items())):
                            return phase_2_slice, phase_2_objective, phase_2_active
        except PricingStateError:
            raise
        except Exception as error:
            queue.put({"phase": "pricing", "pricing_stage": "phase2", "error": str(error),
                       "solve_reported": phase_2_reported})

        return primary

    @staticmethod
    def _report_status(model, queue, pricing_stage="primary"):
        raw_status = model.solution.get_status()
        reported_feasible = model.solution.is_primal_feasible()
        state = map_cplex_mip_status(
            raw_status, has_feasible_solution=reported_feasible
        )
        objective = None
        best_bound = None
        if pricing_stage == "primary":
            if state.has_feasible_solution:
                try:
                    objective = SlaveSolver._finite_value(model.solution.get_objective_value())
                except Exception:
                    # Report the completed solve even if objective extraction fails.
                    # The caller still extracts the objective under the existing contract.
                    pass
            if state.model_status == PAVER.MODEL_STATUS_OPTIMAL:
                best_bound = objective
            elif (state.model_status in {PAVER.MODEL_STATUS_FEASIBLE, PAVER.MODEL_STATUS_NO_SOLUTION}
                  and state.termination_status != PAVER.TERMINATION_ERROR):
                try:
                    best_bound = SlaveSolver._finite_value(model.solution.MIP.get_best_objective())
                except Exception:
                    # Missing telemetry must not change pricing's feasible-column contract.
                    pass
        queue.put({
            "phase": "pricing", "pricing_stage": pricing_stage,
            "raw_status": raw_status, "state": state,
            "objective": objective, "best_bound": best_bound,
        })
        return state.has_feasible_solution

    @staticmethod
    def _finite_value(value):
        if (isinstance(value, Real) and not isinstance(value, bool)
                and math.isfinite(value) and abs(value) < cplex.infinity):
            return float(value)
        return None


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
                      item_width, slice_height, *,
                      use_pricing_second_phase=None):
    return _SOLVER.solve(
        model, queue, manual_interruption, bin_width, item_height, item_width,
        slice_height,
        use_pricing_second_phase=use_pricing_second_phase,
    )


def refine_slave_model(model, queue, bin_width, item_height, item_width,
                       slice_height, primary, remaining_time=None):
    return _SOLVER.refine(model, queue, bin_width, item_height, item_width,
                          slice_height, primary, remaining_time)
