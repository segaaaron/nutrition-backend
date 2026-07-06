"""Gout condition gate — ConditionGate Strategy.

Moves the inline Layer 1 gout filter into the registry so it composes
consistently with all other condition gates.

Excludes recipes tagged `organ_meat` or `shellfish` — the two highest-purine
categories that most reliably elevate serum urate. Other dietary urate
contributors (red meat, some legumes) have weaker evidence; catalog tagging
does not yet support fine-grained purine scoring.

Source: FitzGerald JD et al., 2020 ACR Guideline for the Management of Gout,
Arthritis Rheumatol 2020;72(6):879-895.

NOVA scope: nutrition planning only.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class GoutGate:
    condition: str = "gout"

    def contribute_sql(self) -> tuple[str, dict[str, object]]:
        sql = "(NOT (r.tags && ARRAY['organ_meat','shellfish']::text[]))"
        return sql, {}
