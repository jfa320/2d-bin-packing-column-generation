"""Restricted LP tests with hand-built configurations, without any pricing."""

from fractions import Fraction
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

cplex = pytest.importorskip("cplex")

from models.quadrant_column_generation import (
    Placement, Quadrant, QuadrantConfiguration,
    build_quadrants, generate_global_discretization,
)
from models.quadrant_column_generation.master_problem import (
    MasterDualExtractor, RestrictedMasterBuilder, RestrictedMasterModel,
)
from utils.paver_constants import PaverConstants as PAVER


@pytest.fixture
def geometry():
    grid = generate_global_discretization(10, 10, 1, 1)
    quadrants = build_quadrants(10, 10, 1, 1).quadrants
    return grid, quadrants


def configuration(quadrants, k, *points):
    return QuadrantConfiguration(
        quadrants[k - 1], tuple(Placement(x, y, 1, 1) for x, y in points),
    )


def pool_for(case, quadrants):
    def conf(k, *points):
        return configuration(quadrants, k, *points)

    return {
        "empty": (),
        "initial": tuple(conf(k) for k in range(1, 5)),
        "one": (conf(1, (0, 0), (1, 0)),),
        "compatible": (conf(1, (0, 0), (1, 0)), conf(4, (8, 8), (9, 9))),
        "incompatible": (conf(1, (0, 8)), conf(2, (0, 8))),
        "same_quadrant": (conf(1, (0, 0), (1, 0)), conf(1, (2, 0), (3, 0))),
        "fractional": (
            conf(1, (0, 8), (8, 0)), conf(2, (0, 8), (8, 8)), conf(3, (8, 0), (8, 8)),
        ),
    }[case]


def coverage(grid, config):
    return set().union(*(grid.covered_points(p) for p in config.placements))


def assert_optimal_primal_and_dual(master, result, expected):
    assert result.error_message is None
    assert result.status.model_status == PAVER.MODEL_STATUS_OPTIMAL
    assert result.status.termination_status == PAVER.TERMINATION_NORMAL
    assert result.proven_optimal
    assert result.raw_cplex_status == 1
    assert result.objective_value == pytest.approx(expected)
    assert result.solve_time_s >= 0
    assert result.model_revision == master.model_revision
    prices = result.duals
    assert prices is not None
    assert prices.model_revision == master.model_revision
    assert set(prices.sigma) == {1, 2, 3, 4}
    grid = master.discretization
    assert set(prices.pi) == {(i, j) for i in grid.I for j in grid.J}
    assert all(value >= -1e-9 for value in prices.sigma.values())
    assert all(value >= -1e-9 for value in prices.pi.values())
    # Strong duality for RHS=1 on every row, with the MAX/<= sign convention.
    assert sum(prices.sigma.values()) + sum(prices.pi.values()) == pytest.approx(expected)
    pairs = list(zip(master.configurations, master.variable_names))
    assert sum(c.item_count * result.lambdas[name] for c, name in pairs) == pytest.approx(expected)
    assert all(value >= -1e-9 for value in result.lambdas.values())
    for k in range(1, 5):
        assert sum(result.lambdas[name] for c, name in pairs if c.quadrant.index == k) <= 1 + 1e-9
    for point in prices.pi:
        assert sum(result.lambdas[name] for c, name in pairs if point in coverage(grid, c)) <= 1 + 1e-9
    for config, name in pairs:
        lhs = prices.sigma[config.quadrant.index] + sum(prices.pi[p] for p in coverage(grid, config))
        assert lhs >= config.item_count - 1e-9
        if result.lambdas[name] > 1e-9:
            assert lhs == pytest.approx(config.item_count)


@pytest.mark.parametrize("case, expected", [
    ("empty", 0), ("initial", 0), ("one", 2), ("compatible", 4),
    ("incompatible", 1), ("same_quadrant", 2), ("fractional", 3),
])
def test_hand_built_pool_objectives_and_dual_signs(geometry, case, expected):
    grid, quadrants = geometry
    with RestrictedMasterBuilder(grid, quadrants).build(
        pool_for(case, quadrants), time_limit_s=2,
    ) as master:
        result = master.solve()
        assert_optimal_primal_and_dual(master, result, expected)
        assert master.extract_duals() == result.duals
        print(case, "objective=", result.objective_value, "sigma=", result.duals.sigma,
              "nonzero pi=", {p: v for p, v in result.duals.pi.items() if abs(v) > 1e-9})


def test_all_global_rows_exist_even_without_columns(geometry):
    grid, quadrants = geometry
    with RestrictedMasterBuilder(grid, quadrants).build(time_limit_s=2) as master:
        assert master.cplex_model.get_problem_type() == cplex.Cplex.problem_type.LP
        assert master.cplex_model.variables.get_num() == 0
        assert master.cplex_model.linear_constraints.get_num() == 4 + len(grid.I) * len(grid.J)
        assert set(master.coverage_rows) == {(i, j) for i in grid.I for j in grid.J}
        assert all(sense == "L" for sense in master.cplex_model.linear_constraints.get_senses())
        assert all(rhs == 1 for rhs in master.cplex_model.linear_constraints.get_rhs())
        assert master.cplex_model.parameters.timelimit.get() == 2
        with pytest.raises(RuntimeError, match="optimally"):
            master.extract_duals()


def test_no_individual_upper_bounds_and_configuration_incidence(geometry):
    grid, quadrants = geometry
    config = configuration(quadrants, 1, (0, 0), (1, 0))
    with RestrictedMasterBuilder(grid, quadrants).build([config], time_limit_s=2) as master:
        model = master.cplex_model
        assert model.get_problem_type() == model.problem_type.LP
        assert model.variables.get_lower_bounds() == [0.0]
        assert model.variables.get_upper_bounds() == [cplex.infinity]
        assert model.objective.get_linear() == [2.0]
        column = model.variables.get_cols(master.variable_names[0])
        names = model.linear_constraints.get_names()
        assert {names[i] for i in column.ind} == {"quadrant_1", "cover_0_0", "cover_1_0"}
        assert column.val == [1.0, 1.0, 1.0]
        result = master.solve()
        assert result.duals.pi[(10, 10)] == 0  # Retained empty border row.


def test_same_quadrant_exclusive_rows_have_positive_sigma(geometry):
    grid, quadrants = geometry
    with RestrictedMasterBuilder(grid, quadrants).build(
        pool_for("same_quadrant", quadrants), time_limit_s=2,
    ) as master:
        result = master.solve()
        assert result.duals.sigma == pytest.approx({1: 2, 2: 0, 3: 0, 4: 0})
        assert all(abs(value) <= 1e-9 for value in result.duals.pi.values())


def test_cross_quadrant_conflict_has_positive_pi_at_the_correct_point(geometry):
    grid, quadrants = geometry
    with RestrictedMasterBuilder(grid, quadrants).build(
        pool_for("incompatible", quadrants), time_limit_s=2,
    ) as master:
        result = master.solve()
        assert result.duals.sigma == pytest.approx({1: 0, 2: 0, 3: 0, 4: 0})
        assert result.duals.pi[(0, 8)] == pytest.approx(1)
        assert all(abs(value) <= 1e-9 for p, value in result.duals.pi.items() if p != (0, 8))


def test_fractional_optimum_is_an_lp_with_correctly_associated_prices(geometry):
    grid, quadrants = geometry
    with RestrictedMasterBuilder(grid, quadrants).build(
        pool_for("fractional", quadrants), time_limit_s=2,
    ) as master:
        result = master.solve()
        assert list(result.lambdas.values()) == pytest.approx([0.5, 0.5, 0.5])
        assert result.objective_value == pytest.approx(3)  # Integer selection would achieve 2.
        assert result.duals.sigma == pytest.approx({1: 0, 2: 0, 3: 0, 4: 0})
        assert {p: v for p, v in result.duals.pi.items() if abs(v) > 1e-9} == pytest.approx(
            {(0, 8): 1, (8, 0): 1, (8, 8): 1},
        )


def test_named_extraction_works_when_row_maps_are_reordered(geometry):
    grid, quadrants = geometry
    with RestrictedMasterBuilder(grid, reversed(quadrants)).build(
        pool_for("fractional", quadrants), time_limit_s=2,
    ) as master:
        result = master.solve()
        prices = MasterDualExtractor().extract(
            master.cplex_model, dict(reversed(list(master.quadrant_rows.items()))),
            dict(reversed(list(master.coverage_rows.items()))), model_revision=master.model_revision,
        )
        assert prices == result.duals


def test_incremental_matches_rebuild_and_invalidates_previous_prices(geometry):
    grid, quadrants = geometry
    pool = pool_for("fractional", quadrants)
    builder = RestrictedMasterBuilder(grid, quadrants)
    with builder.build(time_limit_s=2) as incremental:
        for count, expected in enumerate((0, 2, 2, 3)):
            if count:
                old_revision = incremental.model_revision
                incremental.add_configuration(pool[count - 1])
                assert incremental.model_revision == old_revision + 1
                with pytest.raises(RuntimeError, match="optimally"):
                    incremental.extract_duals()
            result = incremental.solve()
            assert_optimal_primal_and_dual(incremental, result, expected)
            with builder.build(pool[:count], time_limit_s=2) as rebuilt:
                rebuilt_result = rebuilt.solve()
                assert_optimal_primal_and_dual(rebuilt, rebuilt_result, expected)
                assert incremental.variable_names == rebuilt.variable_names
                assert incremental.coverage_rows == rebuilt.coverage_rows
                if count == 3:  # This case has unique duals; earlier prefixes need not.
                    assert result.duals == rebuilt_result.duals


def test_exact_duplicates_reuse_variables_but_quadrant_assignments_remain_distinct(geometry):
    grid, quadrants = geometry
    first, other_quadrant = pool_for("incompatible", quadrants)
    with RestrictedMasterBuilder(grid, quadrants).build([first], time_limit_s=2) as master:
        result = master.solve()
        assert master.add_configuration(first) == master.variable_names[0]
        assert master.model_revision == result.model_revision
        assert master.extract_duals() == result.duals
        master.add_configuration(other_quadrant)
        assert len(master.variable_names) == 2
        assert master.cplex_model.variables.get_upper_bounds() == [cplex.infinity] * 2
        assert master.solve().objective_value == 1


def test_original_and_rotated_rectangles_share_coverage_constraints():
    grid = generate_global_discretization(20, 20, 3, 2)
    quadrants = build_quadrants(20, 20, 3, 2).quadrants
    normal = QuadrantConfiguration(quadrants[0], (Placement(16, 16, 3, 2),))
    rotated = QuadrantConfiguration(quadrants[3], (Placement(16, 16, 2, 3, True),))
    with RestrictedMasterBuilder(grid, quadrants).build([normal, rotated], time_limit_s=2) as master:
        assert_optimal_primal_and_dual(master, master.solve(), 1)


@pytest.mark.parametrize("kind", ["wrong_dimensions", "other_quadrant", "not_a_configuration"])
def test_invalid_column_is_rejected_without_changing_the_solved_master(geometry, kind):
    grid, quadrants = geometry
    if kind == "wrong_dimensions":
        bad = QuadrantConfiguration(quadrants[0], (Placement(0, 0, 2, 1),))
    elif kind == "other_quadrant":
        other = build_quadrants(11, 11, 1, 1).quadrants[0]
        bad = QuadrantConfiguration(other, (Placement(0, 0, 1, 1),))
    else:
        bad = object()
    with RestrictedMasterBuilder(grid, quadrants).build(time_limit_s=2) as master:
        result = master.solve()
        with pytest.raises((TypeError, ValueError)):
            master.add_configuration(bad)
        assert master.model_revision == 0
        assert master.variable_names == ()
        assert master.extract_duals() == result.duals


def test_off_grid_placement_is_rejected_even_if_geometrically_valid():
    grid = generate_global_discretization(20, 20, 3, 2)
    quadrants = build_quadrants(20, 20, 3, 2).quadrants
    off_grid = QuadrantConfiguration(quadrants[0], (Placement(1, 0, 3, 2),))
    with RestrictedMasterBuilder(grid, quadrants).build(time_limit_s=2) as master:
        with pytest.raises(ValueError, match="global discretization"):
            master.add_configuration(off_grid)
        assert master.variable_names == ()


@pytest.mark.parametrize("limit", [0, -1, True, None, float("inf"), float("nan")])
def test_invalid_time_limits_are_input_errors(geometry, limit):
    grid, quadrants = geometry
    with pytest.raises(ValueError, match="time_limit_s"):
        RestrictedMasterBuilder(grid, quadrants).build(time_limit_s=limit)


def test_invalid_quadrants_are_rejected(geometry):
    grid, quadrants = geometry
    for invalid in ((), quadrants[:1], (quadrants[0],) * 4):
        with pytest.raises(ValueError, match="four applicable quadrants"):
            RestrictedMasterBuilder(grid, invalid)
    outside = Quadrant(4, Fraction(8), Fraction(8), Fraction(11), Fraction(10), True, True)
    with pytest.raises(ValueError, match="inside the global pallet"):
        RestrictedMasterBuilder(grid, (*quadrants[:3], outside))


def fake_master(geometry, raw_status=1, feasible=True):
    grid, quadrants = geometry
    solution = SimpleNamespace(
        get_status=Mock(return_value=raw_status), is_primal_feasible=Mock(return_value=feasible),
        get_objective_value=Mock(return_value=0), get_values=Mock(return_value=[]),
        get_dual_values=Mock(side_effect=lambda names: [0.0] * len(names)),
    )
    model = SimpleNamespace(solve=Mock(), end=Mock(), solution=solution,
                            variables=SimpleNamespace(add=Mock()))
    return RestrictedMasterModel(model, grid, quadrants,
                                 {k: f"quadrant_{k}" for k in range(1, 5)}, {(0, 0): "cover_0_0"})


@pytest.mark.parametrize("raw, feasible", [(11, True), (11, False), (3, False), (2, True), (999, True)])
def test_nonoptimal_lp_never_returns_duals_or_prices_from_a_previous_solve(geometry, raw, feasible):
    with fake_master(geometry) as master:
        assert master.solve().duals is not None
        solution = master.cplex_model.solution
        solution.get_status.return_value = raw
        solution.is_primal_feasible.return_value = feasible
        solution.get_dual_values.reset_mock()
        result = master.solve()
        assert not result.proven_optimal
        assert result.duals is None
        solution.get_dual_values.assert_not_called()
        with pytest.raises(RuntimeError, match="optimally"):
            master.extract_duals()
        with pytest.raises(RuntimeError, match="primal-valid LP"):
            MasterDualExtractor().extract(master.cplex_model, {}, {}, model_revision=0)


def test_failed_incremental_update_requires_rebuilding_and_never_reuses_prices(geometry):
    _, quadrants = geometry
    with fake_master(geometry) as master:
        assert master.solve().duals is not None
        master.cplex_model.variables.add.side_effect = RuntimeError("update failed")
        with pytest.raises(RuntimeError, match="update failed"):
            master.add_configuration(configuration(quadrants, 1, (0, 0)))
        with pytest.raises(RuntimeError, match="rebuild"):
            master.extract_duals()
        with pytest.raises(RuntimeError, match="rebuild"):
            master.solve()


def test_solver_error_is_explicit_and_closing_releases_resources(geometry):
    master = fake_master(geometry)
    with master:
        master.cplex_model.solve.side_effect = cplex.exceptions.CplexSolverError("LP failed")
        result = master.solve()
        assert result.objective_value is None
        assert result.duals is None
        assert result.status.termination_status == PAVER.TERMINATION_ERROR
        assert "LP failed" in result.error_message
    master.close()
    master.cplex_model.end.assert_called_once()
    with pytest.raises(RuntimeError, match="closed"):
        master.solve()
