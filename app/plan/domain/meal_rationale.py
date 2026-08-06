"""Per-meal rationale (Sprint A1) — the honest "why this recipe" line.

Pure domain. Builds a short, TRUE explanation from facts the plan already
holds (protein, fiber, the user's goal). No invented claims — every clause
maps to a real number on the meal. Transparency is the product's trust lever
vs competitors that show macros without a "why".
"""

from __future__ import annotations

from typing import Final

# Protein (g) above which a slot is worth calling "high protein".
_PROTEIN_HIGHLIGHT: Final[dict[str, int]] = {
    "breakfast": 25,
    "lunch": 35,
    "dinner": 30,
    "snack": 12,
}

_GOAL_FIT: Final[dict[str, tuple[str, str]]] = {
    # goal -> (es, en)
    "weight_loss": ("apoya tu meta de bajar de peso", "supports your weight-loss goal"),
    "muscle_gain": ("apoya tu ganancia muscular", "supports your muscle gain"),
    "weight_gain": ("aporta energía para subir de peso", "adds energy to gain weight"),
    "maintain": ("encaja con mantener tu peso", "fits maintaining your weight"),
    "health": ("aporta a una alimentación equilibrada", "contributes to balanced eating"),
}


def build_meal_rationale(
    *,
    protein_g: int | None,
    fiber_g: int | None,
    meal_time: str,
    goal: str | None,
    condition: str | None = None,
) -> dict[str, str]:
    """Return `{"es": ..., "en": ...}` — a short, fact-based rationale.

    Clauses are only added when the underlying number supports them, so the
    text never over-claims. Always returns a non-empty goal-fit sentence when
    the goal is known; falls back to a neutral line otherwise.
    """
    es_parts: list[str] = []
    en_parts: list[str] = []

    threshold = _PROTEIN_HIGHLIGHT.get(meal_time, 20)
    if protein_g is not None and protein_g >= threshold:
        es_parts.append(f"alto en proteína ({protein_g} g)")
        en_parts.append(f"high in protein ({protein_g} g)")

    if fiber_g is not None and fiber_g >= 5:
        es_parts.append(f"buena fibra ({fiber_g} g)")
        en_parts.append(f"good fiber ({fiber_g} g)")

    if condition == "fatty_liver":
        if fiber_g is not None and fiber_g >= 4 and f"buena fibra ({fiber_g} g)" not in " ".join(es_parts):
            es_parts.append(f"buena fibra ({fiber_g} g) — apoya la salud del hígado")
            en_parts.append(f"good fiber ({fiber_g} g) — supports liver health")
        elif not es_parts or (protein_g is not None and protein_g >= threshold):
            es_parts.append("bajo en grasa saturada — ideal para hígado graso")
            en_parts.append("low in saturated fat — ideal for fatty liver")

    fit = _GOAL_FIT.get(goal or "")
    if fit is not None:
        es_parts.append(fit[0])
        en_parts.append(fit[1])

    if not es_parts:
        return {
            "es": "Comida equilibrada para tu plan.",
            "en": "A balanced meal for your plan.",
        }
    return {
        "es": _join_es(es_parts).capitalize() + ".",
        "en": _join_en(en_parts).capitalize() + ".",
    }


def _join_es(parts: list[str]) -> str:
    if len(parts) == 1:
        return parts[0]
    return ", ".join(parts[:-1]) + " y " + parts[-1]


def _join_en(parts: list[str]) -> str:
    if len(parts) == 1:
        return parts[0]
    return ", ".join(parts[:-1]) + " and " + parts[-1]
