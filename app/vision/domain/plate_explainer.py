"""Deterministic plate explanation — the "algorithm" half of the hybrid.

The vision LLM classifies each detected item into a closed ``FoodGroup``
(AI half, ~2 extra output tokens per item). This module turns those items
into a grouped per-ingredient kcal breakdown plus a localized user-facing
summary — pure code, zero extra AI cost, fully unit-testable.

i18n: es/en templates only (MVP locales, D4). Unknown locale → es.
PII: operates on detected item names only; nothing user-identifying.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.vision.domain.entities import DetectedFoodItem, FoodGroup

# Display order: macro relevance for a nutrition explanation (protein and
# vegetables first — what users care about — sweets/beverages last).
_GROUP_ORDER: tuple[FoodGroup, ...] = (
    "protein",
    "vegetable",
    "grain",
    "fruit",
    "dairy",
    "fat",
    "sweet",
    "beverage",
    "other",
)

_GROUP_LABELS: dict[str, dict[FoodGroup, tuple[str, str]]] = {
    # locale -> group -> (singular, plural)
    "es": {
        "protein": ("proteína", "proteínas"),
        "vegetable": ("vegetal", "vegetales"),
        "grain": ("cereal/carbohidrato", "cereales/carbohidratos"),
        "fruit": ("fruta", "frutas"),
        "dairy": ("lácteo", "lácteos"),
        "fat": ("grasa", "grasas"),
        "sweet": ("dulce", "dulces"),
        "beverage": ("bebida", "bebidas"),
        "other": ("otro", "otros"),
    },
    "en": {
        "protein": ("protein", "proteins"),
        "vegetable": ("vegetable", "vegetables"),
        "grain": ("grain/carb", "grains/carbs"),
        "fruit": ("fruit", "fruits"),
        "dairy": ("dairy", "dairy items"),
        "fat": ("fat", "fats"),
        "sweet": ("sweet", "sweets"),
        "beverage": ("beverage", "beverages"),
        "other": ("other", "others"),
    },
}


@dataclass(slots=True)
class GroupBreakdown:
    group: FoodGroup
    label: str
    items: list[DetectedFoodItem] = field(default_factory=list)

    @property
    def total_kcal(self) -> int:
        return sum(i.kcal for i in self.items)


@dataclass(slots=True)
class PlateExplanation:
    groups: list[GroupBreakdown]
    total_kcal: int
    summary: str


def _label(locale: str, group: FoodGroup, n: int) -> str:
    labels = _GROUP_LABELS.get(locale, _GROUP_LABELS["es"])
    singular, plural = labels[group]
    return singular if n == 1 else plural


def explain_plate(items: list[DetectedFoodItem], locale: str = "es") -> PlateExplanation:
    """Group detected items by food_group and compose a localized summary.

    Items without a ``food_group`` (legacy cached jobs predating the prompt
    bump) fall into ``"other"`` so old jobs keep rendering.
    """
    loc = locale if locale in _GROUP_LABELS else "es"
    by_group: dict[FoodGroup, list[DetectedFoodItem]] = {}
    for it in items:
        group: FoodGroup = it.food_group or "other"
        by_group.setdefault(group, []).append(it)

    groups = [
        GroupBreakdown(group=g, label=_label(loc, g, len(by_group[g])), items=by_group[g])
        for g in _GROUP_ORDER
        if g in by_group
    ]
    total = sum(i.kcal for i in items)

    if not items:
        summary = (
            "No se detectaron alimentos en la foto."
            if loc == "es"
            else "No food items were detected in the photo."
        )
        return PlateExplanation(groups=[], total_kcal=0, summary=summary)

    parts: list[str] = []
    for gb in groups:
        # Prefix each item with its unit count when >1 so the summary reads
        # "2× carne, 4× rebanada de tomate" instead of a bare name — the
        # per-item detail the user sees for a multi-unit plate.
        names = ", ".join(
            f"{i.count}× {i.name}" if i.count > 1 else i.name for i in gb.items
        )
        parts.append(f"{len(gb.items)} {gb.label} ({names}: {gb.total_kcal} kcal)")

    if loc == "es":
        summary = f"Tu plato tiene {'; '.join(parts)}. Total estimado: {total} kcal."
    else:
        summary = f"Your plate has {'; '.join(parts)}. Estimated total: {total} kcal."
    return PlateExplanation(groups=groups, total_kcal=total, summary=summary)
