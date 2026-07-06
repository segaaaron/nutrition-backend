"""Celiac condition gate — H2.5 ConditionGate Strategy.

Filters Layer 1 candidate recipes for users with `celiac` (declared by
user; app does NOT diagnose):
  - Allergen array must NOT contain `gluten` (already enforced by existing
    allergen Layer 1 filter when user adds `gluten` to allergies — this
    gate reinforces for users who only checked the `celiac` condition chip
    without also adding `gluten` allergen).

UI behavior (mobile contract): toggling `Celiaquía` chip should auto-add
`gluten` to allergies. This gate is the server-side safety net if mobile
misses that wiring.

Catalog readiness (2026-06-01):
- 106 recipes `recommended_for: celiac` (all verified GF ingredients)
- 1 recipe `contraindicated_for: celiac`
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CeliacGate:
    condition: str = "celiac"

    def contribute_sql(self) -> tuple[str, dict[str, object]]:
        sql = "(NOT (r.allergens && ARRAY['gluten']::allergen_enum[]))"
        return sql, {}
