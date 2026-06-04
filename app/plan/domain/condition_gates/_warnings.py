"""D15 — Condition gate warning collector.

Pregnancy and lactation gates apply COALESCE-based filters on
folate_ug / iron_mg / calcium_mg. Catalog backfill of these columns is
still in progress (2026-06-03 — see `docs/PROJECT_STATE.md`). Until the
backfill is 100% complete, NULL → 0 → recipe excluded. The filter remains
fail-closed (safe), but the user can silently end up with an empty
candidate pool.

This module exposes a `WarningCollector` that gates push markers into
during plan generation, plus a `MicronutrientDataIncompleteWarning`
dataclass for the marker payload. The plan output (`plan/presentation`
schema, when wired) surfaces these via `warnings[]`.

Pure domain. No framework imports. Decimal not relevant (categorical
markers only).
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class MicronutrientDataIncompleteWarning:
    """Marker emitted when a condition gate's micronutrient filter may
    reject otherwise-eligible recipes solely due to NULL/missing data.

    Attributes:
        condition: the condition under which the gate fired (e.g.
            "pregnancy", "lactation"). Matches the gate's `condition`.
        column: the recipe column being filtered (e.g. "folate_ug").
        code: stable machine-readable code for client/API consumers.
    """

    condition: str
    column: str
    code: str = "micronutrient_data_incomplete"

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "condition": self.condition, "column": self.column}


@dataclass
class WarningCollector:
    """Append-only sink for warnings, deduped by (condition, column, code).

    Used by gates' `emit_warnings(collector)` hook. Plan-generation use case
    instantiates one collector per plan, passes it to every active gate,
    then projects `[w.to_dict() for w in collector.items]` into the
    response's `warnings[]` array.
    """

    items: list[MicronutrientDataIncompleteWarning] = field(default_factory=list)

    def add(self, warning: MicronutrientDataIncompleteWarning) -> None:
        key = (warning.condition, warning.column, warning.code)
        for existing in self.items:
            if (existing.condition, existing.column, existing.code) == key:
                return
        self.items.append(warning)
