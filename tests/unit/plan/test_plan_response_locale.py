"""Unit tests for plan response locale projection (Phase 2 T2.3).

We exercise the pure projection helpers (`_localize_name`,
`_localize_description`, `_to_resp`) directly — no DB, no FastAPI. This
mirrors the acceptance scenarios from
``docs/handoff/2026-06-05-i18n-runtime-locale-propagation-plan.md`` §Phase 2
without the testcontainer overhead (the full HTTP round-trip is covered by
the integration suite in ``tests/integration/plan/test_plan_response_locale.py``).

Locale precedence is fully validated at the FastAPI layer by the
``LocaleDep`` resolution chain (D1 / D4); here we focus on the surface
that consumes the resolved locale.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from app.plan.domain.entities import Plan, PlanDay, PlanMeal
from app.plan.presentation.router import (
    _localize_description,
    _localize_name,
    _RecipeData,
    _to_resp,
)

# Local alias mirroring the _RecipeData record returned by _load_recipe_translations.
_Entry = _RecipeData


def _entry(
    name_en: str = "",
    name_map: dict[str, str] | None = None,
    desc_en: str | None = None,
    desc_map: dict[str, str] | None = None,
) -> _Entry:
    return _RecipeData(
        name_en=name_en,
        name_translations=name_map or {},
        description_en=desc_en,
        description_translations=desc_map or {},
        image_url=None,
        prep_min=None,
        instructions_en=[],
        instructions_translations={},
        fiber_g=None,
        sugar_g=None,
        sodium_mg=None,
        sat_fat_g=None,
        tags=[],
        allergens=[],
        components=[],
    )


def _make_plan() -> tuple[Plan, list[UUID]]:
    """Build a minimal Plan with one day + one meal pointing to a recipe.

    Returns the plan and the list of recipe_ids used so the test can build
    a matching translation map.
    """
    rid = uuid4()
    plan_id = uuid4()
    day_id = uuid4()
    meal_id = uuid4()
    meal = PlanMeal(
        id=meal_id,
        plan_day_id=day_id,
        meal_time="lunch",
        recipe_id=rid,
        kcal=600,
        protein_g=40,
        carbs_g=60,
        fat_g=20,
        completed=False,
        swapped_from=None,
    )
    day = PlanDay(
        id=day_id,
        plan_id=plan_id,
        day_index=0,
        date=datetime.now(UTC).date(),
        completed=False,
        meals=[meal],
    )
    plan = Plan(
        id=plan_id,
        user_id=uuid4(),
        type="day",
        total_days=1,
        current_day=1,
        status="active",
        goal="maintenance",
        meals_per_day=1,
        preferences=[],
        kcal_target=2000,
        version=0,
        created_at=datetime.now(UTC),
        days=[day],
        water_view=None,
    )
    return plan, [rid]


def test_localize_name_returns_locale_when_present() -> None:
    rid = uuid4()
    translations: dict[UUID, _Entry] = {
        rid: _entry("Grilled Chicken", {"es": "Pollo a la Plancha", "en": "Grilled Chicken"}),
    }
    assert _localize_name(rid, translations, "es") == "Pollo a la Plancha"
    assert _localize_name(rid, translations, "en") == "Grilled Chicken"


def test_localize_name_falls_back_to_es_before_en_when_locale_missing() -> None:
    # BE-6: an absent locale translation falls to the Spanish translation
    # BEFORE the raw name_en, so name and description stay in the same language
    # (never English name + Spanish description).
    rid = uuid4()
    translations: dict[UUID, _Entry] = {
        rid: _entry("Grilled Chicken", {"es": "Pollo a la Plancha"}),
    }
    assert _localize_name(rid, translations, "en") == "Pollo a la Plancha"


def test_localize_name_falls_back_to_en_when_locale_missing() -> None:
    rid = uuid4()
    translations: dict[UUID, _Entry] = {rid: _entry("Grilled Chicken")}
    assert _localize_name(rid, translations, "es") == "Grilled Chicken"


def test_localize_name_returns_none_for_missing_recipe() -> None:
    rid = uuid4()
    empty: dict[UUID, _Entry] = {}
    assert _localize_name(rid, empty, "es") is None
    assert _localize_name(None, empty, "es") is None


def test_localize_description_locale_priority_then_es_then_en_fallback() -> None:
    rid = uuid4()
    # Has both es and en translations → each locale returns its own.
    both = {rid: _entry("EN", {}, "English description", {"es": "Descripción", "en": "English description"})}
    assert _localize_description(rid, both, "es") == "Descripción"
    assert _localize_description(rid, both, "en") == "English description"
    # BE-6: only es translation → 'en' falls to es (not the raw description_en,
    # which is Spanish for many catalog rows and would mix languages).
    es_only = {rid: _entry("EN", {}, "raw en field", {"es": "Descripción"})}
    assert _localize_description(rid, es_only, "en") == "Descripción"
    # No translations at all → raw description_en.
    none = {rid: _entry("EN", {}, "raw en field", {})}
    assert _localize_description(rid, none, "en") == "raw en field"


def test_localize_description_none_when_no_description() -> None:
    rid = uuid4()
    translations: dict[UUID, _Entry] = {rid: _entry("EN")}
    assert _localize_description(rid, translations, "es") is None


@pytest.mark.parametrize(
    ("locale", "expected_name"),
    [("es", "Pollo a la Plancha"), ("en", "Grilled Chicken")],
)
def test_to_resp_projects_recipe_name_per_locale(locale: str, expected_name: str) -> None:
    plan, [rid] = _make_plan()
    translations: dict[UUID, _Entry] = {
        rid: _entry(
            "Grilled Chicken",
            {"es": "Pollo a la Plancha", "en": "Grilled Chicken"},
            "Lean protein dinner",
            {"es": "Cena alta en proteínas", "en": "Lean protein dinner"},
        ),
    }
    resp = _to_resp(plan, translations=translations, locale=locale)  # type: ignore[arg-type]
    assert resp.days[0].lunch is not None
    assert resp.days[0].lunch.name_localized == expected_name


def test_to_resp_handles_missing_translations_gracefully() -> None:
    plan, _ = _make_plan()
    empty: dict[UUID, _Entry] = {}
    resp = _to_resp(plan, translations=empty, locale="es")
    assert resp.days[0].lunch is not None
    assert resp.days[0].lunch.name_localized is None
    assert resp.days[0].lunch.description_localized is None


def test_to_resp_default_locale_is_spanish() -> None:
    """Anonymous fallback (D4) — when caller omits locale, default to "es"."""
    plan, [rid] = _make_plan()
    translations: dict[UUID, _Entry] = {
        rid: _entry("Grilled Chicken", {"es": "Pollo a la Plancha", "en": "Grilled Chicken"}),
    }
    resp = _to_resp(plan, translations=translations)
    assert resp.days[0].lunch is not None
    assert resp.days[0].lunch.name_localized == "Pollo a la Plancha"
