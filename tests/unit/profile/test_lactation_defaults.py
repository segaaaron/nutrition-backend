"""Schema-level defaults for lactation/pregnancy chips on mobile onboarding.

iOS / Android chips do NOT collect the `is_exclusively_breastfeeding` or
`trimester` follow-up fields. The schema validator back-fills them with the
safer IOM DRI 2002 baseline (exclusive lactation, third trimester) instead
of rejecting the payload with a 422.

Backward compat: if a client explicitly sends `false` or a different
trimester, the validator preserves the explicit value.
"""

from __future__ import annotations

from app.profile.presentation.schemas import OnboardingRequest


def _base_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "name": "Test Mother",
        "age": 30,
        "sex": "female",
        "weight_kg": "65.0",
        "height_m": "1.65",
        "goal": "maintain",
        "activity_level": "lightly_active",
        "dietary_pattern": "omnivore",
    }
    payload.update(overrides)
    return payload


def test_lactation_without_flag_defaults_exclusive() -> None:
    req = OnboardingRequest(
        **_base_payload(medical_conditions=["lactation"])  # type: ignore[arg-type]
    )
    assert req.is_exclusively_breastfeeding is True


def test_lactation_with_explicit_false_preserved() -> None:
    """Partial lactation (False) must be preserved — defaults must not
    clobber explicit client intent."""
    req = OnboardingRequest(
        **_base_payload(  # type: ignore[arg-type]
            medical_conditions=["lactation"],
            is_exclusively_breastfeeding=False,
        )
    )
    assert req.is_exclusively_breastfeeding is False


def test_lactation_with_explicit_true_preserved() -> None:
    req = OnboardingRequest(
        **_base_payload(  # type: ignore[arg-type]
            medical_conditions=["lactation"],
            is_exclusively_breastfeeding=True,
        )
    )
    assert req.is_exclusively_breastfeeding is True


def test_pregnancy_without_trimester_defaults_third() -> None:
    req = OnboardingRequest(
        **_base_payload(medical_conditions=["pregnancy"])  # type: ignore[arg-type]
    )
    assert req.trimester == "third"


def test_pregnancy_with_explicit_first_preserved() -> None:
    req = OnboardingRequest(
        **_base_payload(  # type: ignore[arg-type]
            medical_conditions=["pregnancy"],
            trimester="first",
        )
    )
    assert req.trimester == "first"


def test_no_lactation_no_default_applied() -> None:
    """If lactation is NOT in conditions, the BF flag stays None — we
    never invent a value out of thin air."""
    req = OnboardingRequest(
        **_base_payload(medical_conditions=[])  # type: ignore[arg-type]
    )
    assert req.is_exclusively_breastfeeding is None
    assert req.trimester is None
