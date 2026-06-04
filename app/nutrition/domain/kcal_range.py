"""KcalRange — ±100 around target (width 200 enforced by VO)."""

from __future__ import annotations

from app.shared.domain.value_objects import KcalRange


def to_range(kcal_target: int) -> KcalRange:
    half = 100
    return KcalRange(min=max(1, kcal_target - half), max=max(201, kcal_target + half))
