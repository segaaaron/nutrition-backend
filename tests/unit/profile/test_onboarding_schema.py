"""Mobile contract validation tests for OnboardingRequest.

Covers every required + conditional field + every documented error path. iOS
and Android implementations should produce request bodies that pass these
exact assertions; mobile QA can mirror the parametrized cases.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.profile.presentation.schemas import OnboardingRequest


def _base_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "name": "Miguel Saravia",
        "age": 30,
        "sex": "male",
        "weight_kg": "72.0",
        "height_m": "1.75",
        "goal": "weight_loss",
        "activity_level": "moderately_active",
        "dietary_pattern": "omnivore",
    }
    payload.update(overrides)
    return payload


# ── happy paths ──────────────────────────────────────────────────────────────


def test_minimum_required_omnivore() -> None:
    body = OnboardingRequest(**_base_payload())  # type: ignore[arg-type]
    assert body.resolved_height_cm == Decimal("175.0")
    assert body.dietary_pattern == "omnivore"


def test_height_cm_alternative_to_height_m() -> None:
    payload = _base_payload()
    del payload["height_m"]
    payload["height_cm"] = "180.0"
    body = OnboardingRequest(**payload)  # type: ignore[arg-type]
    assert body.resolved_height_cm == Decimal("180.0")


def test_athlete_with_bodyfat() -> None:
    body = OnboardingRequest(
        **_base_payload(  # type: ignore[arg-type]
            activity_level="extra_active",
            bodyfat_pct="12.5",
        )
    )
    assert body.bodyfat_pct == Decimal("12.5")


@pytest.mark.parametrize("pattern", ["omnivore", "pescatarian", "vegetarian", "vegan"])
def test_all_dietary_patterns_accepted(pattern: str) -> None:
    OnboardingRequest(**_base_payload(dietary_pattern=pattern))  # type: ignore[arg-type]


def test_celiac_writes_both_condition_and_gluten_allergen() -> None:
    """UI chip "Celiaquía" → server expects BOTH 'celiac' in conditions AND
    'gluten' in allergies. Mobile sends both."""
    body = OnboardingRequest(
        **_base_payload(  # type: ignore[arg-type]
            medical_conditions=["celiac"],
            allergies=["gluten"],
        )
    )
    assert "celiac" in body.medical_conditions
    assert "gluten" in body.allergies


def test_colesterol_alto_maps_to_dyslipidemia() -> None:
    """UI chip "Colesterol alto" → backend enum 'dyslipidemia' (NOT hyperchol)."""
    body = OnboardingRequest(
        **_base_payload(  # type: ignore[arg-type]
            medical_conditions=["dyslipidemia"],
        )
    )
    assert "dyslipidemia" in body.medical_conditions


def test_lactation_with_breastfeeding_status_exclusive() -> None:
    body = OnboardingRequest(
        **_base_payload(  # type: ignore[arg-type]
            medical_conditions=["lactation"],
            is_exclusively_breastfeeding=True,
        )
    )
    assert body.is_exclusively_breastfeeding is True


def test_lactation_partial_breastfeeding() -> None:
    body = OnboardingRequest(
        **_base_payload(  # type: ignore[arg-type]
            medical_conditions=["lactation"],
            is_exclusively_breastfeeding=False,
        )
    )
    assert body.is_exclusively_breastfeeding is False


def test_pregnancy_with_trimester() -> None:
    body = OnboardingRequest(
        **_base_payload(  # type: ignore[arg-type]
            medical_conditions=["pregnancy"],
            trimester="second",
        )
    )
    assert body.trimester == "second"


# ── refuse paths (mobile must surface these as UI errors) ─────────────────────


def test_allergen_freetext_refuses() -> None:
    """ANY non-empty other_allergy → server refuses plan.
    Mobile must show: 'Tu alergia personalizada requiere revisión manual.'"""
    with pytest.raises(ValidationError) as ei:
        OnboardingRequest(**_base_payload(other_allergy="ajonjolí"))  # type: ignore[arg-type]
    assert "allergen_unmapped_requires_review" in str(ei.value)


def test_allergen_freetext_whitespace_only_passes() -> None:
    """Pure whitespace doesn't trigger refuse — strip-equivalence."""
    OnboardingRequest(**_base_payload(other_allergy="   "))  # type: ignore[arg-type]


def test_height_missing_both_refuses() -> None:
    payload = _base_payload()
    del payload["height_m"]
    with pytest.raises(ValidationError) as ei:
        OnboardingRequest(**payload)  # type: ignore[arg-type]
    assert "height_required" in str(ei.value)


def test_pregnancy_without_trimester_refuses() -> None:
    with pytest.raises(ValidationError) as ei:
        OnboardingRequest(
            **_base_payload(  # type: ignore[arg-type]
                medical_conditions=["pregnancy"],
            )
        )
    assert "trimester_required_for_pregnancy" in str(ei.value)


def test_lactation_without_breastfeeding_flag_refuses() -> None:
    with pytest.raises(ValidationError) as ei:
        OnboardingRequest(
            **_base_payload(  # type: ignore[arg-type]
                medical_conditions=["lactation"],
            )
        )
    assert "breastfeeding_status_required_for_lactation" in str(ei.value)


@pytest.mark.parametrize("age", [12, 17, 81, 100])
def test_age_outside_18_80_refuses(age: int) -> None:
    with pytest.raises(ValidationError):
        OnboardingRequest(**_base_payload(age=age))  # type: ignore[arg-type]


@pytest.mark.parametrize("weight", ["29.9", "250.1"])
def test_weight_outside_30_250_refuses(weight: str) -> None:
    with pytest.raises(ValidationError):
        OnboardingRequest(**_base_payload(weight_kg=weight))  # type: ignore[arg-type]


@pytest.mark.parametrize("height_m", ["1.19", "2.41"])
def test_height_m_outside_1_20_2_40_refuses(height_m: str) -> None:
    with pytest.raises(ValidationError):
        OnboardingRequest(**_base_payload(height_m=height_m))  # type: ignore[arg-type]


def test_missing_dietary_pattern_refuses() -> None:
    payload = _base_payload()
    del payload["dietary_pattern"]
    with pytest.raises(ValidationError):
        OnboardingRequest(**payload)  # type: ignore[arg-type]


def test_unknown_dietary_pattern_refuses() -> None:
    with pytest.raises(ValidationError):
        OnboardingRequest(**_base_payload(dietary_pattern="keto"))  # type: ignore[arg-type]


def test_unknown_condition_refuses() -> None:
    with pytest.raises(ValidationError):
        OnboardingRequest(**_base_payload(medical_conditions=["alzheimer"]))  # type: ignore[arg-type]


def test_unknown_allergen_refuses() -> None:
    with pytest.raises(ValidationError):
        OnboardingRequest(**_base_payload(allergies=["mango"]))  # type: ignore[arg-type]


def test_extra_field_refuses() -> None:
    """Strict mode — mobile cannot smuggle unknown fields."""
    with pytest.raises(ValidationError):
        OnboardingRequest(**_base_payload(secret_field="hax"))  # type: ignore[arg-type]  # noqa: S106 — `secret_field` is a test-only kwarg name asserting strict-mode rejection, not a credential


def test_other_condition_freetext_persists_does_not_refuse() -> None:
    """Free-text condition is allowed (PII column) — NOT a refuse path. Just
    not routed to condition Layer1 filter. Mobile must show warning UI."""
    body = OnboardingRequest(**_base_payload(other_condition="alergia al maíz"))  # type: ignore[arg-type]
    assert body.other_condition == "alergia al maíz"


# ── conversion / round-trip ──────────────────────────────────────────────────


def test_height_m_to_cm_conversion_precision() -> None:
    body = OnboardingRequest(**_base_payload(height_m="1.83"))  # type: ignore[arg-type]
    assert body.resolved_height_cm == Decimal("183.0")


def test_height_cm_wins_when_both_present() -> None:
    body = OnboardingRequest(
        **_base_payload(  # type: ignore[arg-type]
            height_m="1.75",
            height_cm="180.0",
        )
    )
    assert body.resolved_height_cm == Decimal("180.0")
