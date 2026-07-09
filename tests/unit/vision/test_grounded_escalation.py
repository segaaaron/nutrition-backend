"""Grounded escalation decision invariants (cost lever 2026-06-11).

The pipeline escalates to the heavy model only when the catalog could not
vouch for the cheap model's output. Key behavioural change vs the old
provider-internal cascade: LOW CONFIDENCE ALONE no longer escalates when
the plate is well-matched — grounding already fixed those macros.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

from app.vision.application.process_vision_job import needs_full_model
from app.vision.domain.entities import DetectedFoodItem

THRESHOLD = 0.7


def _item(conf: float, *, matched: bool) -> DetectedFoodItem:
    return DetectedFoodItem(
        name="x",
        estimated_amount_g=Decimal("100"),
        kcal=200,
        protein_g=10,
        carbs_g=20,
        fat_g=5,
        confidence=conf,
        food_group="other",
        matched_food_id=uuid4() if matched else None,
    )


def test_empty_always_escalates() -> None:
    assert needs_full_model([], conf_threshold=THRESHOLD) == (True, "empty")


def test_garbage_confidence_escalates_even_if_matched() -> None:
    items = [_item(0.9, matched=True), _item(0.2, matched=True)]
    escalate, reason = needs_full_model(items, conf_threshold=THRESHOLD)
    assert escalate and reason == "very_low_item_confidence"


def test_low_confidence_but_well_matched_does_not_escalate() -> None:
    # The saving: old cascade escalated here (avg 0.6 < 0.7); grounding
    # already replaced these items' macros with audited values.
    items = [_item(0.6, matched=True), _item(0.6, matched=True), _item(0.6, matched=True)]
    assert needs_full_model(items, conf_threshold=THRESHOLD) == (False, "")


def test_low_confidence_and_unmatched_does_not_escalate() -> None:
    # Confidence 0.6 is above _ESCALATE_MIN_ITEM_CONF=0.35.
    # Unmatched items at mid-confidence no longer escalate — USDA group-average
    # fallback covers nutrition uncertainty without spending on gpt-4o.
    items = [_item(0.6, matched=False), _item(0.6, matched=False), _item(0.6, matched=True)]
    assert needs_full_model(items, conf_threshold=THRESHOLD) == (False, "")


def test_high_confidence_unmatched_does_not_escalate() -> None:
    # Confident cheap-model output is accepted even without catalog
    # backup — same acceptance rule the old cascade applied.
    items = [_item(0.85, matched=False), _item(0.9, matched=False)]
    assert needs_full_model(items, conf_threshold=THRESHOLD) == (False, "")
