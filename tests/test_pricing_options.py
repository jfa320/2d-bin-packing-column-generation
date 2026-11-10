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


@pytest.mark.parametrize("enabled", [False, True])
def test_legacy_alias_selects_all_flags_and_warns(monkeypatch, enabled):
    for name in FLAG_NAMES:
        monkeypatch.setattr(config, name.upper(), not enabled)
    with pytest.warns(DeprecationWarning, match="finalization_heuristics"):
        options = resolve_pricing_heuristics(enabled)
    assert options.as_kwargs() == dict.fromkeys(FLAG_NAMES, enabled)


@pytest.mark.parametrize("name", FLAG_NAMES)
@pytest.mark.parametrize("enabled", [False, True])
def test_legacy_alias_cannot_be_mixed_with_independent_flags(name, enabled):
    with pytest.raises(ValueError, match="cannot be combined"):
        resolve_pricing_heuristics(True, **{name: enabled})


@pytest.mark.parametrize("name", FLAG_NAMES)
@pytest.mark.parametrize("invalid", [0, 1, "False"])
def test_invalid_override_or_config_fails(name, invalid, monkeypatch):
    with pytest.raises(ValueError, match=name):
        resolve_pricing_heuristics(**{name: invalid})
    monkeypatch.setattr(config, name.upper(), invalid)
    with pytest.raises(ValueError, match=name):
        resolve_pricing_heuristics()


@pytest.mark.parametrize("invalid", [0, 1, "False"])
def test_invalid_alias_fails(invalid):
    with pytest.raises(ValueError, match="finalization_heuristics"):
        resolve_pricing_heuristics(invalid)
