"""ADR-0028 D1 — dietary_pattern is optional; backend defaults to omnivore.

Covers:
  - Schema accepts payload without dietary_pattern (None).
  - CompleteOnboarding defaults to 'omnivore' when None.
  - Structured warning log is emitted (PII-safe: user_id + goal only).
  - Explicit dietary_pattern is respected (no warning).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest

from app.core.event_bus import EventBus
from app.profile.application.use_cases import CompleteOnboarding
from app.profile.domain.entities import UserProfile
from app.profile.presentation.schemas import OnboardingRequest


class _InMemoryProfileRepo:
    def __init__(self) -> None:
        self.store: dict[UUID, UserProfile] = {}

    async def get(self, user_id: UUID) -> UserProfile | None:
        return self.store.get(user_id)

    async def upsert(self, profile: UserProfile) -> None:
        self.store[profile.user_id] = profile


def _onboarding_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "age": 30,
        "sex": "male",
        "weight_kg": Decimal("72.0"),
        "height_cm": Decimal("175"),
        "goal": "weight_loss",
        "activity_level": "moderately_active",
    }
    payload.update(overrides)
    return payload


def test_schema_accepts_missing_dietary_pattern() -> None:
    body = OnboardingRequest(
        age=30,
        sex="male",
        weight_kg=Decimal("72.0"),
        height_m=Decimal("1.75"),
        goal="weight_loss",
        activity_level="moderately_active",
    )
    assert body.dietary_pattern is None


def test_schema_accepts_explicit_dietary_pattern() -> None:
    body = OnboardingRequest(
        age=30,
        sex="male",
        weight_kg=Decimal("72.0"),
        height_m=Decimal("1.75"),
        goal="weight_loss",
        activity_level="moderately_active",
        dietary_pattern="vegan",
    )
    assert body.dietary_pattern == "vegan"


@pytest.mark.asyncio
async def test_use_case_defaults_to_omnivore_when_none(
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo = _InMemoryProfileRepo()
    uc = CompleteOnboarding(profiles=repo, bus=EventBus())
    user_id = uuid4()

    result = await uc(
        user_id=user_id,
        payload=_onboarding_payload(dietary_pattern=None),
    )

    assert result.dietary_pattern == "omnivore"
    # Structlog routes the warning to stdout (filtering bound logger
    # bypasses stdlib `logging`); we assert on captured stdout.
    out = capsys.readouterr().out
    assert "dietary_pattern_defaulted_to_omnivore" in out


@pytest.mark.asyncio
async def test_use_case_respects_explicit_pattern_no_warning(
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo = _InMemoryProfileRepo()
    uc = CompleteOnboarding(profiles=repo, bus=EventBus())

    result = await uc(
        user_id=uuid4(),
        payload=_onboarding_payload(dietary_pattern="vegan"),
    )

    assert result.dietary_pattern == "vegan"
    out = capsys.readouterr().out
    assert "dietary_pattern_defaulted_to_omnivore" not in out


@pytest.mark.asyncio
async def test_default_warning_pii_safe(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """PII grep: warning must NOT include name, email, biometrics."""
    repo = _InMemoryProfileRepo()
    uc = CompleteOnboarding(profiles=repo, bus=EventBus())

    await uc(
        user_id=uuid4(),
        payload=_onboarding_payload(
            name="Personally Identifiable Name",
            dietary_pattern=None,
        ),
    )

    out = capsys.readouterr().out
    # Only the structured warning line should reference the user_id+goal;
    # PII fields must not leak.
    assert "dietary_pattern_defaulted_to_omnivore" in out
    assert "Personally Identifiable Name" not in out
    # Biometrics field names should not appear in the warning payload.
    warning_lines = [
        line
        for line in out.splitlines()
        if "dietary_pattern_defaulted_to_omnivore" in line
    ]
    for line in warning_lines:
        assert "weight_kg" not in line
        assert "height_cm" not in line
