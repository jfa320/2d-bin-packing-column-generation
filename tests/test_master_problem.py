"""Small CPLEX regressions for the continuous/integer master contract."""

from queue import Queue

import cplex
import pytest

from models.column_generation.master_problem import (
    IncrementalMasterModel, MasterModelBuilder, solve_master_model,
)
from objects import Item, Slice


def unit_column(*positions):
    return Slice(height=1, width=3, items=[
        Item(height=1, width=1, position_x=x, position_y=0)
        for x in positions
    ])


@pytest.fixture
def build_master():
    models = []

    def build(columns, width=3, height=1):
        model = MasterModelBuilder().build(3, columns, height, width, 1, 1)
        for setter in (model.set_log_stream, model.set_results_stream,
                       model.set_warning_stream, model.set_error_stream):
            setter(None)
        model.parameters.threads.set(1)
        model.parameters.randomseed.set(0)
        models.append(model)
        return model

    yield build
    for model in models:
        model.end()


def solve(model, relaxed=True):
    return solve_master_model(model, Queue(), None, relaxed, 0)


def assert_cell_duals_cover_columns(model, columns, duals, objective):
    assert sum(duals["pi"].values()) == pytest.approx(objective)
    for column in columns:
        cells = MasterModelBuilder._slice_cells(column)
        price = sum(duals["pi"].get(f"({x},{y})", 0.0) for x, y in cells)
        assert column.get_total_items() - price <= 1e-9
        upper = model.variables.get_upper_bounds(f"p_{column.get_id()}")
        assert upper == (cplex.infinity if column.get_total_items() else 1.0)


def test_single_rectangle_relaxation_prices_occupied_cells(build_master):
    column = Slice(height=2, width=3, items=[
        Item(height=2, width=3, position_x=0, position_y=0)])
    model = build_master([column], width=3, height=2)

    objective, duals, _ = solve(model)

    assert objective == pytest.approx(1)
    assert_cell_duals_cover_columns(model, [column], duals, objective)


def test_incremental_and_rebuilt_relaxations_have_consistent_duals(build_master):
    seed = unit_column(0)
    columns = [seed]
    model = build_master(columns)
    incremental = IncrementalMasterModel(model, columns, height_bin=1, width_bin=3)
    objective, duals, _ = solve(model)
    assert_cell_duals_cover_columns(model, columns, duals, objective)

    # Exercise a new cell row, an existing row and a zero-objective empty column.
    for column in (unit_column(0, 1), unit_column(1), unit_column()):
        assert incremental.add_slice(column)
        columns.append(column)
        objective, duals, _ = solve(model)
        assert_cell_duals_cover_columns(model, columns, duals, objective)

    rebuilt = build_master(columns)
    rebuilt_objective, rebuilt_duals, _ = solve(rebuilt)
    assert objective == rebuilt_objective == pytest.approx(2)
    assert_cell_duals_cover_columns(rebuilt, columns, rebuilt_duals, rebuilt_objective)


def test_integer_solve_restores_binarity_after_fractional_relaxation(build_master):
    # Three pairwise-overlapping patterns: LP chooses each at 1/2, IP only one.
    columns = [unit_column(0, 1), unit_column(1, 2), unit_column(0, 2)]
    model = build_master(columns)
    objective, duals, _ = solve(model)
    assert objective == pytest.approx(3)
    assert model.solution.get_values() == pytest.approx([0.5] * 3)
    assert_cell_duals_cover_columns(model, columns, duals, objective)

    integer_objective, integer_duals, _ = solve(model, relaxed=False)
    fresh_objective, _, _ = solve(build_master(columns), relaxed=False)

    assert integer_objective == fresh_objective == 2
    assert integer_duals is None
    assert model.variables.get_types() == ["B"] * 3
    assert model.variables.get_upper_bounds() == [1.0] * 3
    # The same public facade can relax the master again without retaining bounds.
    objective, duals, _ = solve(model)
    assert objective == pytest.approx(3)
    assert_cell_duals_cover_columns(model, columns, duals, objective)
