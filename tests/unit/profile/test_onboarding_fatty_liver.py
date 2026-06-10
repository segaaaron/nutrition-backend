"""OnboardingRequest schema test — `fatty_liver` is an accepted MobileCondition.

Mobile clients (iOS / Android) can now send `medical_conditions: ["fatty_liver"]`
without the request being refused by the closed enum.
"""

from __future__ import annotations

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


def test_fatty_liver_accepted_as_medical_condition() -> None:
    body = OnboardingRequest(
        **_base_payload(medical_conditions=["fatty_liver"])  # type: ignore[arg-type]
    )
    assert "fatty_liver" in body.medical_conditions


def test_fatty_liver_combined_with_diabetes_t2_accepted() -> None:
    """NAFLD frequently co-occurs with T2D in LatAm. Closed enum must allow
    both in the same payload (subject to max_length=6)."""
    body = OnboardingRequest(
        **_base_payload(  # type: ignore[arg-type]
            medical_conditions=["fatty_liver", "diabetes_t2"],
        )
    )
    assert set(body.medical_conditions) == {"fatty_liver", "diabetes_t2"}


def test_fatty_liver_does_not_require_extra_fields() -> None:
    """Unlike pregnancy/lactation, NAFLD has no required conditional field."""
    OnboardingRequest(
        **_base_payload(medical_conditions=["fatty_liver"])  # type: ignore[arg-type]
    )


def test_unknown_condition_still_refused() -> None:
    """Regression: closed enum unchanged for other unknown values."""
    with pytest.raises(ValidationError):
        OnboardingRequest(
            **_base_payload(medical_conditions=["nafld"])  # type: ignore[arg-type]
        )
