"""Legacy fields `other_allergy` / `other_condition` MUST not break onboarding.

iOS 2026-06+ removes both UI inputs, so production traffic should be zero.
The previous behaviour raised a hard-stop 422 on any non-empty
`other_allergy`, which produced an unrecoverable dead-end for any client
that hadn't been updated yet. Backend now tolerates legacy payloads:

* `other_allergy` non-empty → warning + silently nulled, plan proceeds.
* `other_condition` non-empty → stored as PII (existing behaviour), info log.
"""

from __future__ import annotations

from decimal import Decimal

from app.profile.presentation.schemas import OnboardingRequest


def _base(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
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


def test_other_allergy_legacy_value_ignored_no_refuse() -> None:
    body = OnboardingRequest(**_base(other_allergy="shrimp"))  # type: ignore[arg-type]
    # Field is nulled — no plan refuse; plan generation proceeds downstream.
    assert body.other_allergy is None


def test_other_allergy_empty_string_ignored() -> None:
    body = OnboardingRequest(**_base(other_allergy=""))  # type: ignore[arg-type]
    assert body.other_allergy in (None, "")


def test_other_condition_legacy_value_persists_as_pii() -> None:
    body = OnboardingRequest(**_base(other_condition="fibromyalgia"))  # type: ignore[arg-type]
    # Free text is preserved (PII column) — NOT routed to Layer1 filter.
    assert body.other_condition == "fibromyalgia"


def test_both_legacy_fields_omitted_works() -> None:
    """Modern iOS path: neither field is sent."""
    body = OnboardingRequest(**_base())  # type: ignore[arg-type]
    assert body.other_allergy is None
    assert body.other_condition is None


def test_legacy_fields_do_not_break_strict_mode() -> None:
    """Strict ConfigDict(extra='forbid') must still allow the deprecated
    fields (they are declared on the model)."""
    body = OnboardingRequest(
        **_base(other_allergy="x", other_condition="y")  # type: ignore[arg-type]
    )
    assert body.other_allergy is None
    assert body.other_condition == "y"
    # Sanity: required biometrics intact.
    assert body.weight_kg == Decimal("72.0")
