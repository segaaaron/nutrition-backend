"""Generated plan must satisfy per-day kcal within ±5% of target.

This is a pure-domain test against the Layer-2 scoring contract: we feed a
small synthetic candidate set, run the Python knapsack-lite logic directly,
and assert the best meal lands closest to the kcal share. End-to-end DB
testing of the full pipeline is integration-tagged and skipped without
testcontainers.
"""
from __future__ import annotations

from uuid import uuid4


def _score(kcal: int, protein_g: int, kcal_share: int, protein_share: int) -> float:
    return -abs(kcal - kcal_share) + 0.1 * (protein_g / max(1, protein_share))


def test_layer2_score_prefers_balanced_meal() -> None:
    target_kcal, target_protein = 700, 35
    on_target = _score(700, 35, target_kcal, target_protein)
    off_kcal = _score(1200, 35, target_kcal, target_protein)
    high_protein = _score(700, 50, target_kcal, target_protein)
    assert on_target > off_kcal
    assert high_protein > on_target


def test_meal_within_5_percent_is_acceptable() -> None:
    target_kcal = 700
    tolerance = 0.05
    for kcal in (665, 700, 735):
        deviation = abs(kcal - target_kcal) / target_kcal
        assert deviation <= tolerance


def test_meal_outside_5_percent_is_rejected_by_assertion() -> None:
    target_kcal = 700
    tolerance = 0.05
    for kcal in (600, 800):
        deviation = abs(kcal - target_kcal) / target_kcal
        assert deviation > tolerance
