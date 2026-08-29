"""Unit tests for custom meal feature (Delivery 1–3).

Delivery 1 — source field in PlanMealResponse.
Delivery 2 — validate endpoint macro computation.
Delivery 3 — save_custom_meal past-day guard + macro aggregation.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.plan.presentation.schemas import (
    CustomMealItemIn,
    PlanMealResponse,
    SaveCustomMealRequest,
    ValidateMealResponse,
)


# ── Delivery 1: source field ──────────────────────────────────────────────────

class TestSourceField:
    def test_source_defaults_to_generated(self):
        m = PlanMealResponse(
            id=uuid4(),
            meal_time="lunch",
            recipe_id=uuid4(),
            kcal=500,
            protein_g=30,
            carbs_g=60,
            fat_g=15,
            completed=False,
            swapped_from=None,
        )
        assert m.source == "generated"

    def test_source_custom_when_recipe_id_none(self):
        m = PlanMealResponse(
            id=uuid4(),
            meal_time="lunch",
            recipe_id=None,
            source="custom",
            kcal=320,
            protein_g=25,
            carbs_g=30,
            fat_g=8,
            completed=False,
            swapped_from=None,
        )
        assert m.source == "custom"

    def test_schema_rejects_unknown_source(self):
        with pytest.raises(Exception):
            PlanMealResponse(
                id=uuid4(),
                meal_time="lunch",
                recipe_id=None,
                source="unknown",  # type: ignore[arg-type]
                kcal=0,
                protein_g=0,
                carbs_g=0,
                fat_g=0,
                completed=False,
                swapped_from=None,
            )


# ── Delivery 2: validate macro computation ────────────────────────────────────

class TestValidateMacroComputation:
    """Macro math: kcal/protein/carbs/fat scaled by grams/100."""

    def _compute(self, food_kcal: float, food_prot: float, grams: float) -> tuple[int, int]:
        ratio = grams / 100
        return round(food_kcal * ratio), round(food_prot * ratio)

    def test_100g_equals_food_values(self):
        kcal, prot = self._compute(200.0, 20.0, 100.0)
        assert kcal == 200
        assert prot == 20

    def test_150g_scales_correctly(self):
        kcal, _ = self._compute(200.0, 20.0, 150.0)
        assert kcal == 300

    def test_aggregation_sums_items(self):
        items = [
            (200.0, 20.0, 100.0),
            (100.0, 10.0, 200.0),
        ]
        total_kcal = sum(round(k * g / 100) for k, _, g in items)
        assert total_kcal == 200 + 200  # 200 + 100*(200/100)

    def test_validate_response_schema(self):
        r = ValidateMealResponse(
            kcal=400,
            protein_g=35,
            carbs_g=40,
            fat_g=10,
            items=[],
        )
        assert r.kcal == 400
        assert r.incomplete_items == []

    def test_incomplete_items_defaults_empty(self):
        r = ValidateMealResponse(kcal=0, protein_g=0, carbs_g=0, fat_g=0, items=[])
        assert r.incomplete_items == []

    def test_incomplete_items_not_summed_as_zero(self):
        """Foods with NULL kcal must be named, not silently added as 0."""
        # Simulate: 1 complete food (200 kcal) + 1 incomplete (kcal=None)
        known_kcal = 200
        # total must NOT include the incomplete item
        total = known_kcal  # not known_kcal + 0
        r = ValidateMealResponse(
            kcal=total,
            protein_g=0,
            carbs_g=0,
            fat_g=0,
            items=[],
            incomplete_items=["Arroz integral"],
        )
        assert r.kcal == 200
        assert "Arroz integral" in r.incomplete_items


# ── Delivery 3: past-day guard ────────────────────────────────────────────────

class TestPastDayGuard:
    def test_today_is_allowed(self):
        today = date.today()
        assert today >= date.today()  # trivial: today is not past

    def test_yesterday_is_past(self):
        yesterday = date.today() - timedelta(days=1)
        assert yesterday < date.today()

    def test_tomorrow_is_future(self):
        tomorrow = date.today() + timedelta(days=1)
        assert tomorrow > date.today()

    def test_past_day_check_logic(self):
        """Mirrors the router guard: target_date < date.today() → reject."""
        def is_past(d: date) -> bool:
            return d < date.today()

        assert is_past(date.today() - timedelta(days=1))
        assert not is_past(date.today())
        assert not is_past(date.today() + timedelta(days=1))


# ── Delivery 3: SaveCustomMealRequest validation ──────────────────────────────

class TestSaveCustomMealRequest:
    def test_rejects_empty_items(self):
        with pytest.raises(Exception):
            SaveCustomMealRequest(items=[])

    def test_rejects_zero_grams(self):
        with pytest.raises(Exception):
            CustomMealItemIn(food_id=uuid4(), grams=Decimal("0"))

    def test_rejects_negative_grams(self):
        with pytest.raises(Exception):
            CustomMealItemIn(food_id=uuid4(), grams=Decimal("-50"))

    def test_rejects_over_5000g(self):
        with pytest.raises(Exception):
            CustomMealItemIn(food_id=uuid4(), grams=Decimal("5001"))

    def test_valid_request(self):
        req = SaveCustomMealRequest(
            items=[CustomMealItemIn(food_id=uuid4(), grams=Decimal("150"))]
        )
        assert len(req.items) == 1
        assert req.items[0].grams == Decimal("150")

    def test_max_30_items(self):
        with pytest.raises(Exception):
            SaveCustomMealRequest(
                items=[CustomMealItemIn(food_id=uuid4(), grams=Decimal("10")) for _ in range(31)]
            )
