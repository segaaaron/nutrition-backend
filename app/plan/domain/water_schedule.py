"""Daily water schedule generator — distributes total_ml across 8 anchored slots.

Slot anchors (locale es-LATAM defaults):

    07:00  Al despertar         weight 2  (kickstart post-overnight dehydration)
    08:30  Pre-desayuno         weight 1
    11:00  Media mañana         weight 1
    13:00  Pre-almuerzo         weight 1
    16:00  Media tarde          weight 2
    19:00  Pre-cena             weight 1
    21:00  Post-cena            weight 2
    23:00  Antes de dormir      weight 1

    Total weight = 11.

Algorithm:
    1. Compute each slot's share = round(weight * total_ml / 11).
    2. Last slot absorbs the rounding remainder so ``sum(slot.ml) == total_ml``
       exactly (no float drift).
    3. Wake slot is guaranteed weight 2 (joint-max) → always >= any other slot
       after proportional scaling.

This is pure / framework-agnostic. Times are clock strings (``HH:MM``) so
the scheduler layer can localise to the user's timezone at delivery.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Final

from app.plan.domain.water_calculator import DEFAULT_GLASS_ML


@dataclass(frozen=True, slots=True)
class WaterSlot:
    """A single timed slot of the daily hydration schedule.

    Attributes:
        time: Clock time, ``HH:MM`` (24h, naive — caller localises).
        ml: Millilitres to drink at this slot (int, > 0 unless redistribution
            zeroed it; never negative).
        label: Human-readable label (Spanish default).
    """

    time: str
    ml: int
    label: str


# (time, label, weight). Sum of weights = 11.
_SLOT_TEMPLATE: Final[tuple[tuple[str, str, int], ...]] = (
    ("07:00", "Al despertar", 2),
    ("08:30", "Pre-desayuno", 1),
    ("11:00", "Media mañana", 1),
    ("13:00", "Pre-almuerzo", 1),
    ("16:00", "Media tarde", 2),
    ("19:00", "Pre-cena", 1),
    ("21:00", "Post-cena", 2),
    ("23:00", "Antes de dormir", 1),
)

_TOTAL_WEIGHT: Final[int] = sum(w for _, _, w in _SLOT_TEMPLATE)  # 11


def build_water_schedule(
    *,
    total_ml: int,
    glass_ml: int = DEFAULT_GLASS_ML,
) -> list[WaterSlot]:
    """Build the daily 8-slot hydration schedule summing exactly to total_ml.

    Args:
        total_ml: Daily target in ml (int, > 0). Must be the value already
            produced by :func:`calculate_water_target` (capped to
            [1500, 4000]).
        glass_ml: Glass size in ml — used only for input validation here;
            slot ml are NOT forced to multiples of ``glass_ml`` since
            proportional redistribution cannot guarantee that.

    Returns:
        List of 8 :class:`WaterSlot`, in chronological order, with
        ``sum(slot.ml) == total_ml`` exactly.

    Raises:
        ValueError: If ``total_ml <= 0`` or ``glass_ml <= 0``.
    """
    if total_ml <= 0:
        raise ValueError(f"total_ml must be > 0, got {total_ml}")
    if glass_ml <= 0:
        raise ValueError(f"glass_ml must be > 0, got {glass_ml}")

    total_d = Decimal(total_ml)
    weight_d = Decimal(_TOTAL_WEIGHT)

    slots: list[WaterSlot] = []
    accumulated = 0
    last_idx = len(_SLOT_TEMPLATE) - 1

    for i, (time_str, label, weight) in enumerate(_SLOT_TEMPLATE):
        if i == last_idx:
            # Last slot absorbs remainder for exact sum invariant.
            ml = total_ml - accumulated
        else:
            share = (Decimal(weight) * total_d / weight_d).quantize(
                Decimal("1"), rounding=ROUND_HALF_EVEN
            )
            ml = int(share)
            accumulated += ml
        slots.append(WaterSlot(time=time_str, ml=ml, label=label))

    return slots
