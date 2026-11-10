"""Resolve independent pricing heuristics, including the legacy API alias."""

from dataclasses import dataclass
import warnings

import config


@dataclass(frozen=True)
class PricingHeuristics:
    second_phase: bool
    final_enrichment: bool
    duplicate_retries: bool

    def as_kwargs(self):
        return {
            "use_pricing_second_phase": self.second_phase,
            "use_pricing_final_enrichment": self.final_enrichment,
            "use_pricing_duplicate_retries": self.duplicate_retries,
        }


def resolve_pricing_heuristics(finalization_heuristics=None, *,
                               use_pricing_second_phase=None,
                               use_pricing_final_enrichment=None,
                               use_pricing_duplicate_retries=None):
    overrides = (use_pricing_second_phase, use_pricing_final_enrichment,
                 use_pricing_duplicate_retries)
    names = ("use_pricing_second_phase", "use_pricing_final_enrichment",
             "use_pricing_duplicate_retries")
    if finalization_heuristics is not None:
        if not isinstance(finalization_heuristics, bool):
            raise ValueError("finalization_heuristics must be a boolean or None")
        if any(value is not None for value in overrides):
            raise ValueError("finalization_heuristics cannot be combined with independent pricing flags")
        warnings.warn(
            "finalization_heuristics is deprecated; use the three independent pricing flags",
            DeprecationWarning, stacklevel=2,
        )
        return PricingHeuristics(*(finalization_heuristics,) * 3)
    values = []
    for name, value in zip(names, overrides):
        value = getattr(config, name.upper()) if value is None else value
        if not isinstance(value, bool):
            raise ValueError(f"{name} must be a boolean or None")
        values.append(value)
    return PricingHeuristics(*values)
