"""Hypertension condition gate — H2.4 ConditionGate Strategy.

Formalizes the existing Layer 1 inline `sodium_mg <= 600` filter into the
Strategy registry pattern. No behavioral change vs prior inline gate;
this exists to keep the registry as the single source of truth for
condition-driven filters.

Catalog readiness (2026-06-01):
- 546 recipes `recommended_for: hypertension`
- 783 recipes `contraindicated_for: hypertension` (high-sodium recipes
  defensively tagged)

NOVA scope: nutrition planning only. No clinical advice.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class HypertensionGate:
    condition: str = "hypertension"

    def contribute_sql(self) -> tuple[str, dict[str, object]]:
        sql = "(COALESCE(r.sodium_mg, 0) <= :ht_sodium_max)"
        params: dict[str, object] = {"ht_sodium_max": 600}
        return sql, params
