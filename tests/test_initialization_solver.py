"""Small CPLEX checks. Run with an external wall-clock timeout."""

from queue import Queue
from types import SimpleNamespace

import pytest

import config
from models.column_generation import column_generation_solver as cg
from models.column_generation.initialization import InitialSliceOptions, generate_mixed_slices
from models.column_generation.master_problem import create_master_model
from models.column_generation.orchestrator_services import (
    InitialSliceGenerator, calculate_slice_height,
)
from models.column_generation.solution_pool import PricingGeometry
from models.common.position_generator import generate_positions_xym
from objects.ConfigData import ConfigData


def test_case7_initial_integer_master_improves_from_six_to_seven():
    xy_x, xy_y = generate_positions_xym(50, 20, 13, 8)
    geometry = PricingGeometry(50, 20, 13, 8, calculate_slice_height(50, 20, 13, 8))
    base = InitialSliceGenerator().generate(50, 20, 13, 8, xy_x, xy_y, 9)
    extras = generate_mixed_slices(base, geometry, xy_x, xy_y, InitialSliceOptions("mixed"))
    for columns, expected in ((base, 6), (base + extras, 7)):
        model = create_master_model(5, columns, 20, 50, 8, 13, xy_x, xy_y)
        try:
            model.set_log_stream(None)
            model.set_results_stream(None)
            model.parameters.threads.set(1)
            model.solve()
            assert model.solution.get_status() == 101
            assert model.solution.get_objective_value() == pytest.approx(expected)
        finally:
            model.end()


@pytest.mark.parametrize("initialization,expect_mixed,expected_initial_lp", [
    (None, False, 6), ("mixed", True, 7),
])
def test_default_homogeneous_and_explicit_mixed_keep_a_single_pricing_instance(
        monkeypatch, initialization, expect_mixed, expected_initial_lp):
    sessions = []
    original = cg.IncrementalPricingModel
    def pricing(*args, **kwargs):
        session = original(*args, **kwargs)
        sessions.append(session)
        return session
    monkeypatch.setattr(cg, "IncrementalPricingModel", pricing)
    monkeypatch.setattr(cg, "export_final_layout", lambda *args: None)
    result = cg.orchestrator(
        Queue(), SimpleNamespace(value=True), 15, 0, ConfigData(50, 20, 13, 8),
        return_structured=True, initialization=initialization, threads=1,
        use_pricing_second_phase=False, use_pricing_final_enrichment=False,
        use_pricing_duplicate_retries=False)
    assert result.execution.termination_status == "Normal"
    if expect_mixed:
        assert result.metrics.initial_mixed_columns > 0
    else:
        assert result.metrics.initial_mixed_columns == 0
    assert result.metrics.initial_lp_value == pytest.approx(expected_initial_lp)
    assert result.metrics.restricted_integer_master == pytest.approx(7)
    assert result.diagnostics.lp_convergence_proven
    assert len(sessions) == 1


def test_mixed_output_is_feasible_after_normalizing_both_axes(monkeypatch):
    layouts = []
    monkeypatch.setattr(cg, "export_final_layout", lambda *args: layouts.extend(args[-1]))
    result = cg.orchestrator(
        Queue(), SimpleNamespace(value=True), 15, 0, ConfigData(4, 6, 2, 3),
        return_structured=True, initialization="mixed", threads=1,
        use_pricing_second_phase=False, use_pricing_final_enrichment=False,
        use_pricing_duplicate_retries=False)
    assert result.execution.termination_status == "Normal"
    assert result.metrics.initial_mixed_columns > 0
    assert result.metrics.restricted_integer_master == pytest.approx(4)
    occupied = set()
    total = 0
    for slice_ in layouts:
        for item in slice_.get_items():
            x, y = item.get_position()
            width, height = item.get_width(), item.get_height()
            assert (width, height) == ((3, 2) if item.get_rotated() else (2, 3))
            assert 0 <= x and x + width <= 4 and 0 <= y and y + height <= 6
            cells = {(a, b) for a in range(x, x + width) for b in range(y, y + height)}
            assert not occupied & cells
            occupied.update(cells)
            total += 1
    assert total == 4


@pytest.mark.parametrize("configured_strategy,override,cap,expected_mixed,expected_lp", [
    ("homogeneous", None, None, 0, 6), ("homogeneous", "mixed", None, 1, 7),
    ("mixed", None, None, 1, 7), ("mixed", "homogeneous", None, 0, 6),
    ("mixed", "mixed", 0, 0, 6),
])
def test_parent_config_and_overrides_survive_spawn(monkeypatch, configured_strategy, override, cap,
                                                 expected_mixed, expected_lp):
    monkeypatch.setattr(config, "INITIALIZATION_STRATEGY", configured_strategy)
    monkeypatch.setattr(config, "INITIAL_MIXED_MAX_COLUMNS", 1)
    result = cg.execute_with_time_limit(
        15, instance=config.get_instance("case7"), initialization=override,
        initial_mixed_max_columns=cap, record_iterations=False, threads=1,
        use_pricing_second_phase=False, use_pricing_final_enrichment=False,
        use_pricing_duplicate_retries=False)
    assert result.execution.termination_status == "Normal", result.execution.error_message
    assert result.metrics.initial_columns == 3 + expected_mixed
    assert result.metrics.initial_mixed_columns == expected_mixed
    assert result.metrics.initial_lp_value == pytest.approx(expected_lp)
    assert result.diagnostics.initial_lp_status.raw_cplex_status == 1
    assert result.metrics.initialization_time_s > 0
    assert result.metrics.cg_time_s >= result.metrics.initialization_time_s
    assert result.metrics.restricted_integer_master == pytest.approx(7)
    assert result.diagnostics.lp_convergence_proven
    assert result.iterations == []
