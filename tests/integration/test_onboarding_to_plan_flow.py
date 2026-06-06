"""ADR-0028 — integration flow: onboarding → plan generation → flag flip.

Gated under `pytest.mark.integration`. Validates the cross-context wiring
contract without requiring a real Postgres+Redis stack:

  1. POST-/me/onboarding equivalent: CompleteOnboarding leaves flag=False.
  2. dietary_pattern omitted → defaults to omnivore + warning log.
  3. PlanCreated event publication flips the flag to True.
  4. Re-emission of PlanCreated is a no-op (idempotent).

The real plan generation pipeline is out of scope for this integration
contract; we publish PlanCreated directly through the same EventBus the
worker would use.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest

from app.core.event_bus import EventBus
from app.plan.domain.events import PlanCreated
from app.profile.application.event_handlers import (
    make_flip_onboarding_on_plan_created,
)
from app.profile.application.use_cases import CompleteOnboarding
from app.profile.domain.entities import UserProfile

pytestmark = pytest.mark.integration


class _Repo:
    def __init__(self) -> None:
        self.store: dict[UUID, UserProfile] = {}

    async def get(self, user_id: UUID) -> UserProfile | None:
        return self.store.get(user_id)

    async def upsert(self, profile: UserProfile) -> None:
        self.store[profile.user_id] = profile


class _FakeSession:
    def __init__(self) -> None:
        self.commits = 0

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        pass

    async def __aenter__(self) -> _FakeSession:
        return self

    async def __aexit__(self, *_a: Any) -> None:
        return None


def _payload(**overrides: Any) -> dict[str, Any]:
    p: dict[str, Any] = {
        "age": 30,
        "sex": "male",
        "weight_kg": Decimal("72.0"),
        "height_cm": Decimal("175"),
        "goal": "weight_loss",
        "activity_level": "moderately_active",
    }
    p.update(overrides)
    return p


@pytest.mark.asyncio
async def test_full_flow_onboarding_to_plan_to_flag_flip(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo = _Repo()
    bus = EventBus()
    user_id = uuid4()

    # Patch SqlProfileRepository inside the handler module to bind to
    # the in-memory repo for this integration scenario.
    class _RepoAdapter:
        def __init__(self, _session: Any) -> None:
            pass

        async def get(self, uid: UUID) -> UserProfile | None:
            return await repo.get(uid)

        async def upsert(self, profile: UserProfile) -> None:
            await repo.upsert(profile)

    monkeypatch.setattr(
        "app.profile.application.event_handlers.SqlProfileRepository",
        _RepoAdapter,
    )

    def _sessionmaker() -> _FakeSession:
        return _FakeSession()

    bus.subscribe(
        PlanCreated, make_flip_onboarding_on_plan_created(_sessionmaker)  # type: ignore[arg-type]
    )

    # Step 1: onboarding without dietary_pattern.
    uc = CompleteOnboarding(profiles=repo, bus=bus)
    profile = await uc(user_id=user_id, payload=_payload())

    assert profile.onboarding_completed is False
    assert profile.dietary_pattern == "omnivore"
    out = capsys.readouterr().out
    assert "dietary_pattern_defaulted_to_omnivore" in out

    # Step 2: simulate worker publishing PlanCreated.
    await bus.publish(
        PlanCreated(
            plan_id=uuid4(),
            user_id=user_id,
            type="weekly",
            total_days=7,
            at=datetime.now(tz=UTC),
        )
    )

    flipped = await repo.get(user_id)
    assert flipped is not None
    assert flipped.onboarding_completed is True

    # Step 3: re-emit PlanCreated → idempotent, flag stays True.
    await bus.publish(
        PlanCreated(
            plan_id=uuid4(),
            user_id=user_id,
            type="weekly",
            total_days=7,
            at=datetime.now(tz=UTC),
        )
    )
    again = await repo.get(user_id)
    assert again is not None
    assert again.onboarding_completed is True
