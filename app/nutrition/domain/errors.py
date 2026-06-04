"""Nutrition bounded-context domain errors.

Surfaced to the API layer via the global `DomainError` -> RFC 7807
translator (`app/core/errors.py`). Each error carries an `extra` dict
that becomes part of the `application/problem+json` payload.
"""

from __future__ import annotations

from decimal import Decimal

from app.core.errors import DomainError


class BmrSafetyFloorViolated(DomainError):
    """H1.4 — kcal_target would land below BMR * 0.9.

    AND/ACSM/Dietitians of Canada Joint Position 2016 (Med Sci Sports
    Exerc 48:543) flags sustained intake below BMR as a RED-S risk and
    a driver of metabolic adaptation. The 0.9 factor adds a 10%
    guardrail margin. We REFUSE to emit a plan in this regime — telemetry
    alone is insufficient for BMR safety.
    """

    http_status = 422
    type_slug = "bmr-safety-floor-violated"
    title = "kcal_target_below_bmr_safety_floor"

    def __init__(self, *, kcal_target: Decimal, floor: Decimal) -> None:
        # Render as ints in the payload (kcal granularity per CLAUDE.md
        # anti-pattern list — "precisión >5 kcal es ilusión de exactitud").
        super().__init__(
            "kcal_target_below_bmr_safety_floor",
            kcal_target=int(kcal_target),
            floor=int(floor),
        )
