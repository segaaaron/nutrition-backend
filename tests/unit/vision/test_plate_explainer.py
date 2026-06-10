"""Unit — deterministic plate explainer (groups + localized summary)."""

from __future__ import annotations

from decimal import Decimal

from app.vision.domain.entities import DetectedFoodItem
from app.vision.domain.plate_explainer import explain_plate


def _item(name: str, kcal: int, group: str | None) -> DetectedFoodItem:
    return DetectedFoodItem(
        name=name,
        estimated_amount_g=Decimal("100"),
        kcal=kcal,
        protein_g=0,
        carbs_g=0,
        fat_g=0,
        confidence=0.9,
        food_group=group,  # type: ignore[arg-type]
    )


def test_groups_ordered_and_totalled() -> None:
    items = [
        _item("arroz blanco", 195, "grain"),
        _item("tomate", 7, "vegetable"),
        _item("pollo a la plancha", 198, "protein"),
        _item("cebolla", 12, "vegetable"),
    ]
    out = explain_plate(items, locale="es")
    assert [g.group for g in out.groups] == ["protein", "vegetable", "grain"]
    veg = next(g for g in out.groups if g.group == "vegetable")
    assert veg.total_kcal == 19
    assert sorted(i.name for i in veg.items) == ["cebolla", "tomate"]
    assert out.total_kcal == 412


def test_summary_es_singular_plural() -> None:
    items = [
        _item("tomate", 7, "vegetable"),
        _item("cebolla", 12, "vegetable"),
        _item("pollo", 198, "protein"),
    ]
    out = explain_plate(items, locale="es")
    assert "2 vegetales" in out.summary
    assert "1 proteína" in out.summary
    assert "Total estimado: 217 kcal" in out.summary


def test_summary_en() -> None:
    items = [_item("chicken", 198, "protein")]
    out = explain_plate(items, locale="en")
    assert "1 protein" in out.summary
    assert "Estimated total: 198 kcal" in out.summary


def test_unknown_locale_falls_back_to_es() -> None:
    items = [_item("tomate", 7, "vegetable")]
    out = explain_plate(items, locale="pt")
    assert "Total estimado" in out.summary


def test_legacy_items_without_group_land_in_other() -> None:
    items = [_item("misterio", 100, None)]
    out = explain_plate(items, locale="es")
    assert [g.group for g in out.groups] == ["other"]
    assert out.total_kcal == 100


def test_empty_items() -> None:
    out = explain_plate([], locale="es")
    assert out.groups == []
    assert out.total_kcal == 0
    assert "No se detectaron" in out.summary
