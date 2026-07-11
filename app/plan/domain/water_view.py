"""Water view for plan responses — schedule + coach-tone message.

Pure presentation-of-domain helper. Reads ``total_ml`` (already produced by
the nutrition bounded context via
:func:`app.plan.domain.water_calculator.calculate_water_target`) and emits a
visual structure suitable for the mobile client:

    * an 8-slot daily schedule (sums exactly to ``total_ml``),
    * a short, encouraging coach-tone message (no nagging, no medical advice).

Single source of truth for the daily target remains
``nutritional_goals.water_ml`` — this helper never recomputes it.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Literal

from app.plan.domain.water_calculator import DEFAULT_GLASS_ML
from app.plan.domain.water_schedule import WaterSlot, build_water_schedule

Locale = Literal["es", "en"]


@dataclass(frozen=True, slots=True)
class WaterView:
    """Composed daily water view ready for serialisation.

    Attributes:
        total_ml: Daily target (mirrors ``nutritional_goals.water_ml``).
        glass_ml: Reference glass size (default 250 ml).
        n_glasses: Ceil(total_ml / glass_ml).
        schedule: 8 chronological slots whose ``ml`` field sums to
            ``total_ml`` exactly.
        message: Short, locale-aware coach message (encouraging tone).
    """

    total_ml: int
    glass_ml: int
    n_glasses: int
    schedule: list[WaterSlot]
    message: str


def _format_litres(total_ml: int) -> str:
    """Render ``total_ml`` as ``X.YL`` using one-decimal banker's rounding."""
    litres = (Decimal(total_ml) / Decimal(1000)).quantize(
        Decimal("0.1"), rounding=ROUND_HALF_EVEN
    )
    return f"{litres}L"


_MESSAGES: dict[str, str] = {
    # COACH_TONE.md — encouraging, never nagging, never medical.
    "es": "Tu meta hoy: {litres} ({n} vasos). Vamos paso a paso.",
    "en": "Today's goal: {litres} ({n} glasses). One sip at a time.",
}


def build_water_view(
    *,
    total_ml: int,
    glass_ml: int = DEFAULT_GLASS_ML,
    locale: str = "es",
) -> WaterView:
    """Assemble the full water view from a stored daily ``total_ml``.

    Args:
        total_ml: Daily water target in ml (int, > 0). Sourced from
            ``nutritional_goals.water_ml``.
        glass_ml: Glass size (default 250). Must be > 0.
        locale: 2-letter locale code (es/pt/en/fr/de). Unknown locales
            fall back to Spanish (NOVA default region: LatAm).

    Returns:
        :class:`WaterView` with schedule (sums == total_ml) and message.

    Raises:
        ValueError: Propagated from :func:`build_water_schedule` when
            ``total_ml <= 0`` or ``glass_ml <= 0``.
    """
    schedule = build_water_schedule(total_ml=total_ml, glass_ml=glass_ml)
    # Integer ceil division — exact, no float drift.
    n_glasses = -(-total_ml // glass_ml)
    template = _MESSAGES.get(locale, _MESSAGES["es"])
    message = template.format(litres=_format_litres(total_ml), n=n_glasses)
    return WaterView(
        total_ml=total_ml,
        glass_ml=glass_ml,
        n_glasses=n_glasses,
        schedule=schedule,
        message=message,
    )
