"""Geometry and selection checks; no optimization models are built or solved."""

import csv
from itertools import product
from pathlib import Path

import pytest

import config
from instances import DEFAULT_INSTANCES
from models.common.position_generator import generate_positions_xym
from models.column_generation import initialization as initial
from models.column_generation.orchestrator_services import (
    InitialSliceGenerator, ProblemNormalizer, calculate_slice_height,
)
from objects.ConfigData import ConfigData
from models.column_generation.solution_pool import (
    InvalidPoolSolution, PricingGeometry, candidate_from_slice, slice_master_key,
)


def seeds(width=50, height=20, item_width=13, item_height=8, *, limit=24):
    width, height = max(width, height), min(width, height)
    item_width, item_height = max(item_width, item_height), min(item_width, item_height)
    xy_x, xy_y = generate_positions_xym(width, height, item_width, item_height)
    geometry = PricingGeometry(width, height, item_width, item_height,
                               calculate_slice_height(width, height, item_width, item_height))
    base = InitialSliceGenerator().generate(
        width, height, item_width, item_height, xy_x, xy_y,
        width * height // (item_width * item_height))
    extras = initial.generate_mixed_slices(
        base, geometry, xy_x, xy_y, initial.InitialSliceOptions("mixed", limit))
    return base, extras, geometry, xy_x, xy_y


def catalog_instances():
    cases = [(name, tuple(case[key] for key in
                         ("bin_width", "bin_height", "item_width", "item_height")))
             for name, case in DEFAULT_INSTANCES.items()]
    path = Path(__file__).resolve().parents[1] / "benchmark_validation_baseline.csv"
    with path.open(newline="", encoding="utf-8-sig") as stream:
        cases.extend((row["instance"], tuple(int(row[key]) for key in ("L", "W", "l", "w")))
                     for row in csv.DictReader(stream))
    return cases


def assert_position_presence_matches_geometry(dimensions):
    """Check placement existence independently of the normal-set arithmetic."""
    width, height, item_width, item_height = dimensions
    fits = ((item_width <= width and item_height <= height)
            or (item_height <= width and item_width <= height))
    problem = ProblemNormalizer().normalize(ConfigData(*dimensions))
    width, height = problem.bin_width, problem.bin_height
    item_width, item_height = problem.item_width, problem.item_height
    normal, rotated = generate_positions_xym(width, height, item_width, item_height)
    assert bool(normal or rotated) == fits, dimensions
    # Squares use only the normal domain; other items retain each feasible orientation.
    assert bool(normal) == (item_width <= width and item_height <= height), dimensions
    assert bool(rotated) == (item_width != item_height
                             and item_height <= width and item_width <= height), dimensions
    for positions in (normal, rotated):
        if positions:
            assert (0, 0) in positions, dimensions


def test_position_presence_exhaustively_for_small_dimensions():
    # All 160,000 original dimension tuples, including tall bins/items and no-fit cases.
    for dimensions in product(range(1, 21), repeat=4):
        assert_position_presence_matches_geometry(dimensions)


@pytest.mark.parametrize("name,dimensions", catalog_instances())
def test_position_presence_matches_geometry_for_catalog_and_benchmark(name, dimensions):
    assert_position_presence_matches_geometry(dimensions)


@pytest.mark.parametrize("name,dimensions", catalog_instances())
def test_enrichment_geometry_domain_and_master_deduplication(name, dimensions):
    base, extras, geometry, xy_x, xy_y = seeds(*dimensions)
    base_keys = {slice_master_key(slice_) for slice_ in base}
    extra_keys = set()
    assert len(extras) <= 24
    for slice_ in extras:
        candidate = candidate_from_slice(slice_, {"pi": {}}, geometry)
        assert candidate.value == slice_.get_total_items()
        assert candidate.master_key not in base_keys | extra_keys
        extra_keys.add(candidate.master_key)
        assert {item.get_rotated() for item in slice_.get_items()} == {False, True}
        assert len({item.get_position_y() for item in slice_.get_items()}) == 1
        for item in slice_.get_items():
            assert item.get_position() in (xy_y if item.get_rotated() else xy_x)


def test_case7_contains_the_complementary_mixed_row_without_changing_base():
    base, extras, geometry, xy_x, xy_y = seeds()
    expected = ((0, 0, "x"), (13, 0, "x"), (26, 0, "x"), (39, 0, "y"))
    assert any(candidate_from_slice(s, {"pi": {}}, geometry).placements == expected
               for s in extras)
    assert len(base) == 3
    assert all(len({i.get_rotated() for i in s.get_items()}) == 1 for s in base)
    assert initial.generate_mixed_slices(
        base, geometry, xy_x, xy_y, initial.InitialSliceOptions()) == []
    default = initial.generate_mixed_slices(
        base, geometry, xy_x, xy_y, initial.resolve_initialization())
    assert default == []


def test_bounded_patterns_are_deterministic_and_cover_both_height_endpoints():
    base, extras, geometry, xy_x, xy_y = seeds(100, 60, 7, 3)
    repeated = initial.generate_mixed_slices(
        base, geometry, list(reversed(sorted(xy_x))), list(reversed(sorted(xy_y))),
        initial.InitialSliceOptions("mixed"))
    assert len(extras) == 24
    assert [slice_master_key(s) for s in extras] == [slice_master_key(s) for s in repeated]
    admissible = {y for _, y in xy_x} & {y for _, y in xy_y}
    chosen = {s.get_items()[0].get_position_y() for s in extras}
    assert len(chosen) == 4
    assert min(admissible) in chosen and max(admissible) in chosen


@pytest.mark.parametrize("limit", [0, 1, 5, 24, 100])
def test_global_limit_counts_only_new_mixed_columns(limit):
    base, extras, geometry, xy_x, xy_y = seeds(100, 60, 7, 3, limit=limit)
    assert len(extras) == min(limit, 24)
    if extras:
        again = initial.generate_mixed_slices(
            base + extras, geometry, xy_x, xy_y, initial.InitialSliceOptions("mixed", limit))
        assert not {slice_master_key(s) for s in again} & {slice_master_key(s) for s in extras}


@pytest.mark.parametrize("dimensions", [(20, 20, 4, 4), (8, 5, 5, 4), (20, 4, 5, 3)])
def test_no_mix_keeps_the_homogeneous_pool(dimensions):
    base, extras, *_ = seeds(*dimensions)
    assert base and extras == []


def test_sparse_position_domains_are_respected():
    geometry = PricingGeometry(10, 10, 4, 3, 3)
    assert initial.generate_mixed_slices(
        [], geometry, {(0, 0)}, {(0, 0)}, initial.InitialSliceOptions("mixed")) == []


def test_geometry_validation_errors_propagate(monkeypatch):
    def invalid(*args, **kwargs):
        raise InvalidPoolSolution("diagnostic retained")
    monkeypatch.setattr(initial, "candidate_from_values", invalid)
    with pytest.raises(InvalidPoolSolution, match="diagnostic retained"):
        seeds()


def test_generator_does_not_construct_cplex(monkeypatch):
    import cplex
    def forbidden(*args, **kwargs):
        pytest.fail("initialization must not construct CPLEX")
    monkeypatch.setattr(cplex, "Cplex", forbidden)
    assert seeds()[1]


def test_config_resolution_and_explicit_overrides(monkeypatch):
    monkeypatch.setattr(config, "INITIALIZATION_STRATEGY", "mixed")
    monkeypatch.setattr(config, "INITIAL_MIXED_MAX_COLUMNS", 3)
    assert initial.resolve_initialization().as_kwargs() == {
        "initialization": "mixed", "initial_mixed_max_columns": 3}
    assert initial.resolve_initialization("homogeneous", 0) == initial.InitialSliceOptions("homogeneous", 0)


@pytest.mark.parametrize("strategy,limit", [("unknown", 24), (True, 24),
                                         ("mixed", -1), ("mixed", True),
                                         ("mixed", 1.5), ("mixed", "2")])
def test_invalid_options_are_rejected(strategy, limit):
    with pytest.raises(ValueError):
        initial.resolve_initialization(strategy, limit)
