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


def test_celiac_handled_via_gluten_allergen_not_condition() -> None:
    """2026-07-09: celiac is no longer a medical condition. A celiac user just
    sends 'gluten' in allergies — the allergen hard-exclude filter enforces the
    exclusion. 'celiac' is rejected by the closed MobileCondition enum."""
    body = OnboardingRequest(
        **_base_payload(  # type: ignore[arg-type]
            medical_conditions=[],
            allergies=["gluten"],
        )
    )
    assert "gluten" in body.allergies
    assert body.medical_conditions == []


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


def test_allergen_freetext_legacy_ignored() -> None:
    """Legacy iOS clients may still send `other_allergy`. Backend tolerates
    it: warns + silently nulls the field, never refuses the plan. iOS
    2026-06+ removes the field entirely so production traffic is zero."""
    body = OnboardingRequest(**_base_payload(other_allergy="ajonjolí"))  # type: ignore[arg-type]
    assert body.other_allergy is None


def test_allergen_freetext_whitespace_only_passes() -> None:
    """Pure whitespace doesn't trigger refuse — strip-equivalence."""
    OnboardingRequest(**_base_payload(other_allergy="   "))  # type: ignore[arg-type]


def test_height_missing_both_refuses() -> None:
    payload = _base_payload()
    del payload["height_m"]
    with pytest.raises(ValidationError) as ei:
        OnboardingRequest(**payload)  # type: ignore[arg-type]
    assert "height_required" in str(ei.value)


def test_pregnancy_without_trimester_defaults_third() -> None:
    """IOM DRI 2002 safer baseline: chip-based onboarding does not collect
    trimester, server defaults to third (+452 kcal/day, highest demand)."""
    req = OnboardingRequest(
        **_base_payload(  # type: ignore[arg-type]
            medical_conditions=["pregnancy"],
        )
    )
    assert req.trimester == "third"


def test_lactation_without_breastfeeding_flag_defaults_exclusive() -> None:
    """IOM DRI 2002 safer baseline: chip-based onboarding does not collect
    the exclusive-vs-parcial flag, server defaults to exclusive (+500 kcal/
    day) to avoid under-feeding lactating mothers."""
    req = OnboardingRequest(
        **_base_payload(  # type: ignore[arg-type]
            medical_conditions=["lactation"],
        )
    )
    assert req.is_exclusively_breastfeeding is True


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


def test_missing_dietary_pattern_accepted_default_omnivore_applied_use_case() -> None:
    """ADR-0028 D1 — `dietary_pattern` is now optional. The schema must
    accept absence; defaulting to `omnivore` happens server-side in
    `CompleteOnboarding` with a structured warning log. iOS MVP form
    does not ask this field."""
    payload = _base_payload()
    del payload["dietary_pattern"]
    body = OnboardingRequest(**payload)  # type: ignore[arg-type]
    assert body.dietary_pattern is None


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


# ── disliked_ingredients (taste-preference exclusion, 2026-07-20) ─────────────


def test_disliked_ingredients_defaults_empty() -> None:
    body = OnboardingRequest(**_base_payload())  # type: ignore[arg-type]
    assert body.disliked_ingredients == []


def test_disliked_ingredients_accepts_freetext_list() -> None:
    body = OnboardingRequest(
        **_base_payload(disliked_ingredients=["brócoli", "cebolla"])  # type: ignore[arg-type]
    )
    assert body.disliked_ingredients == ["brócoli", "cebolla"]
    # Flows into the payload the profile use-case persists via setattr.
    assert body.model_dump()["disliked_ingredients"] == ["brócoli", "cebolla"]
