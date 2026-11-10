from itertools import product

import pytest

import config
from models.column_generation.pricing_options import resolve_pricing_heuristics


FLAG_NAMES = ("use_pricing_second_phase", "use_pricing_final_enrichment",
              "use_pricing_duplicate_retries")
COMBINATIONS = list(product((False, True), repeat=3))


def test_pricing_heuristics_default_to_disabled():
    assert resolve_pricing_heuristics().as_kwargs() == dict.fromkeys(FLAG_NAMES, False)
    assert not hasattr(config, "USE_PRACTICAL_CG_ENHANCEMENTS")


@pytest.mark.parametrize("flags", COMBINATIONS)
def test_runtime_config_and_independent_overrides(monkeypatch, flags):
    for name, enabled in zip(FLAG_NAMES, flags):
        monkeypatch.setattr(config, name.upper(), enabled)
    assert resolve_pricing_heuristics().as_kwargs() == dict(zip(FLAG_NAMES, flags))
    for name, enabled in zip(FLAG_NAMES, flags):
        expected = dict(zip(FLAG_NAMES, flags))
        expected[name] = not enabled
        assert resolve_pricing_heuristics(**{name: not enabled}).as_kwargs() == expected


@pytest.mark.parametrize("name", FLAG_NAMES)
@pytest.mark.parametrize("invalid", [0, 1, "False"])
def test_invalid_override_or_config_fails(name, invalid, monkeypatch):
    with pytest.raises(ValueError, match=name):
        resolve_pricing_heuristics(**{name: invalid})
    monkeypatch.setattr(config, name.upper(), invalid)
    with pytest.raises(ValueError, match=name):
        resolve_pricing_heuristics()
