"""Lactose intolerance condition gate — ConditionGate Strategy.

Mirrors the CeliacGate pattern: when the user declares lactose intolerance
the server-side gate excludes dairy recipes even if the client forgot to
auto-add the `dairy` allergen. Belt-and-suspenders contract with mobile.

NOVA scope: nutrition planning only. App does NOT diagnose.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class LactoseIntoleranceGate:
    condition: str = "lactose_intolerance"

    def contribute_sql(self) -> tuple[str, dict[str, object]]:
        sql = "(NOT (r.allergens && ARRAY['dairy']::allergen_enum[]))"
        return sql, {}
