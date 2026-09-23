"""Restricted master problem for column generation.

The public functions at the bottom are compatibility facades.  The actual
responsibilities are split into model construction, solving and dual mapping.
"""

import cplex

from utils.cplex_helpers import add_constraint_set, add_variables
from utils.paver_constants import PaverConstants
from utils.status_normalizer import map_cplex_lp_status, map_cplex_mip_status

MODEL_NAME = "Model5Master"
DISABLE_DUPLICATE_CONSTRAINT_CHECK = True
PAVER = PaverConstants


def calculate_occupied_positions(position, width, height):
    x, y = position
    return {
        (x + dx, y + dy)
        for dx in range(width) for dy in range(height)
    }


class MasterModelBuilder:
    """Build the restricted master without solving or logging it."""

    def __init__(self, disable_duplicate_constraint_check=DISABLE_DUPLICATE_CONSTRAINT_CHECK):
        self.disable_duplicate_constraint_check = disable_duplicate_constraint_check

    def build(self, max_time, slices, height_bin, width_bin, height_item,
              width_item, positions_xy_x=None, positions_xy_y=None):
        del height_item, width_item, positions_xy_x, positions_xy_y
        model = cplex.Cplex()
        model.set_problem_type(cplex.Cplex.problem_type.MILP)
        model.parameters.timelimit.set(max_time)
        model.parameters.preprocessing.presolve.set(0)
        model.parameters.lpmethod.set(1)

        variable_names = [f"p_{slice_.get_id()}" for slice_ in slices]
        objective_coefficients = [slice_.get_total_items() for slice_ in slices]
        add_variables(
            model, variable_names, objective_coefficients,
            model.variables.type.binary,
        )
        model.objective.set_sense(model.objective.sense.maximize)

        cells_by_slice = {
            slice_.get_id(): self._slice_cells(slice_)
            for slice_ in slices
        }
        positions = [
            (x, y) for x in range(width_bin) for y in range(height_bin)
        ]
        added_constraints = set()
        for position in positions:
            covering = [
                slice_ for slice_ in slices
                if position in cells_by_slice[slice_.get_id()]
            ]
            if not covering:
                continue
            add_constraint_set(
                model,
                [1.0] * len(covering),
                [f"p_{slice_.get_id()}" for slice_ in covering],
                1.0,
                "L",
                added_constraints,
                f"consItem_{position[0]}_{position[1]}",
                self.disable_duplicate_constraint_check,
            )
        return model

    @staticmethod
    def _slice_cells(slice_):
        cells = set()
        for item in slice_.get_items():
            if item.get_position_x() is None or item.get_position_y() is None:
                continue
            cells.update(calculate_occupied_positions(
                item.get_position(), item.get_width(), item.get_height()
            ))
        return cells


class DualExtractor:
    """Map CPLEX master constraint names to pricing dual prices."""

    def extract(self, model):
        prices = {"pi": {}}
        dual_values = model.solution.get_dual_values()
        constraint_names = model.linear_constraints.get_names()
        for name, dual_value in zip(constraint_names, dual_values):
            if not name.startswith("consItem_"):
                continue
            _, a, b = name.split("_")
            prices["pi"][f"({a},{b})"] = dual_value
        return prices


class MasterSolver:
    """Solve either the relaxed or integer restricted master."""

    def __init__(self, dual_extractor=None):
        self.dual_extractor = dual_extractor or DualExtractor().extract

    def solve(self, model, queue, manual_interruption, relax_model, initial_time):
        del manual_interruption, initial_time
        model.set_problem_type(
            cplex.Cplex.problem_type.LP
            if relax_model else cplex.Cplex.problem_type.MILP
        )
        model.solve()
        raw_status = model.solution.get_status()
        reported_feasible = model.solution.is_primal_feasible()
        mapper = map_cplex_lp_status if relax_model else map_cplex_mip_status
        state = mapper(raw_status, has_feasible_solution=reported_feasible)
        feasible = state.has_feasible_solution
        objective_value = (
            model.solution.get_objective_value() if feasible else None
        )
        queue.put({
            "phase": "lp" if relax_model else "ip",
            "state": state,
            "raw_status": raw_status,
            "objective": objective_value,
        })
        if not feasible:
            return None, None, []

        if not relax_model:
            rounded = round(objective_value)
            if abs(objective_value - rounded) <= 1e-6:
                objective_value = rounded

        dual_values = None
        if (
            relax_model
            and state.model_status == PAVER.MODEL_STATUS_OPTIMAL
            and state.termination_status == PAVER.TERMINATION_NORMAL
        ):
            dual_values = self.dual_extractor(model)

        active_variables = [
            name for name in model.variables.get_names()
            if model.solution.get_values(name) > 0.5
        ]
        return objective_value, dual_values, active_variables


_MODEL_BUILDER = MasterModelBuilder()


def create_master_model(max_time, slices, height_bin, width_bin, height_item,
                        width_item, positions_xy_x, positions_xy_y):
    return _MODEL_BUILDER.build(
        max_time, slices, height_bin, width_bin, height_item, width_item,
        positions_xy_x, positions_xy_y,
    )


def get_dual_values(model):
    return DualExtractor().extract(model)


def solve_master_model(model, queue, manual_interruption, relax_model, initial_time):
    # Resolve the facade at call time so existing monkeypatch-based clients keep
    # control of dual extraction during tests and experiments.
    return MasterSolver(dual_extractor=get_dual_values).solve(
        model, queue, manual_interruption, relax_model, initial_time
    )
