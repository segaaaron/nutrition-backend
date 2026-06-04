"""Hypertension condition gate — H2.4 ConditionGate Strategy.

Formalizes the existing Layer 1 inline `sodium_mg <= 600` filter into the
Strategy registry pattern. No behavioral change vs prior inline gate;
this exists to keep the registry as the single source of truth for
condition-driven filters.

Catalog readiness (2026-06-01):
- 546 recipes `recommended_for: hypertension`
- 783 recipes `contraindicated_for: hypertension` (high-sodium recipes
  defensively tagged)

NOVA scope: nutrition planning only.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class HypertensionGate:
    condition: str = "hypertension"

    def contribute_sql(self) -> tuple[str, dict[str, object]]:
        # R6 fail-closed (2026-06-03): sodium_mg is the critical column for
        # hypertension safety; NULL means the row is incomplete, not safe.
        sql = "(r.sodium_mg IS NOT NULL AND r.sodium_mg <= :ht_sodium_max)"
        # Source: 2017 ACC/AHA Guideline for High Blood Pressure +
        # WHO 2023 sodium guideline — daily Na <2000 mg target → ≤600 mg
        # per meal (3 meal pattern with margin for snacks/condiments).
        params: dict[str, object] = {"ht_sodium_max": 600}
        return sql, params
