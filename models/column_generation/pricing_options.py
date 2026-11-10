"""Resolve the three independent pricing heuristics."""

from dataclasses import dataclass

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


def resolve_pricing_heuristics(*, use_pricing_second_phase=None,
                               use_pricing_final_enrichment=None,
                               use_pricing_duplicate_retries=None):
    overrides = (use_pricing_second_phase, use_pricing_final_enrichment,
                 use_pricing_duplicate_retries)
    names = ("use_pricing_second_phase", "use_pricing_final_enrichment",
             "use_pricing_duplicate_retries")
    values = []
    for name, value in zip(names, overrides):
        value = getattr(config, name.upper()) if value is None else value
        if not isinstance(value, bool):
            raise ValueError(f"{name} must be a boolean or None")
        values.append(value)
    return PricingHeuristics(*values)
