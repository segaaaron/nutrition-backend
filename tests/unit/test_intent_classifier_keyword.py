"""Unit — keyword-side of the intent classifier (no OpenAI)."""
from __future__ import annotations

import pytest

from app.coach.domain.value_objects import Intent
from app.coach.infrastructure.intent_classifier import HybridIntentClassifier


@pytest.mark.anyio
async def test_template_intents_match() -> None:
    c = HybridIntentClassifier()
    cases = [
        ("¿cuál es mi plan de hoy?", Intent.VIEW_TODAY_PLAN),
        ("próxima comida?", Intent.NEXT_MEAL),
        ("cómo va mi racha?", Intent.STREAK_STATUS),
        ("cuánta agua llevo hoy?", Intent.WATER_PROGRESS),
        ("¿cuánta proteína me falta?", Intent.PROTEIN_REMAINING),
        ("registra que tomé agua", Intent.MARK_WATER),
    ]
    for text, expected in cases:
        intent, conf = await c.classify(text=text, locale="es", user_id=None)
        assert intent == expected, f"{text!r} → {intent}"


@pytest.mark.anyio
async def test_medical_short_circuit() -> None:
    c = HybridIntentClassifier()
    intent, conf = await c.classify(
        text="tengo dolor de cabeza y tomo metformina", locale="es", user_id=None,
    )
    assert intent == Intent.MEDICAL_REDIRECT
    assert conf == 1.0
