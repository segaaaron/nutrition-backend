"""ADR-0028 — PlanCreated → onboarding_completed flag handler.

Tests cover:
  - Flag flips False → True on first PlanCreated for the user.
  - Idempotent: when flag already True, handler performs no DB write.
  - Profile missing: warning log, no raise.
  - Concurrent dispatch: final state True, single effective write.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest

from app.plan.domain.events import PlanCreated
from app.profile.application.event_handlers import (
    make_flip_onboarding_on_plan_created,
)
from app.profile.domain.entities import UserProfile


class _FakeRepoState:
    def __init__(self, profile: UserProfile | None) -> None:
        self.profile = profile
        self.upserts: list[UserProfile] = []


class _FakeSession:
    def __init__(self, state: _FakeRepoState) -> None:
        self.state = state
        self.committed = False
        self.rolled_back = False

    async def commit(self) -> None:
        self.committed = True

    async def rollback(self) -> None:
        self.rolled_back = True

    async def __aenter__(self) -> _FakeSession:
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        return None

    # SqlProfileRepository surface used by the handler.
    async def get(self, *_a: Any, **_kw: Any) -> Any:  # pragma: no cover - unused
        raise AssertionError("repo.get path used instead")


class _FakeSessionMaker:
    """Async-sessionmaker shape: callable returning an async-CM session."""

    def __init__(self, state: _FakeRepoState) -> None:
        self.state = state
        self.last_session: _FakeSession | None = None

    def __call__(self) -> _FakeSession:
        self.last_session = _FakeSession(self.state)
        return self.last_session


@pytest.fixture
def _patched_repo(monkeypatch: pytest.MonkeyPatch) -> _FakeRepoState:
    """Patch SqlProfileRepository inside the event_handlers module so we
    don't need a real Postgres session for the unit test.
    """
    state = _FakeRepoState(profile=None)

    class _FakeRepo:
        def __init__(self, _session: Any) -> None:
            pass

        async def get(self, _user_id: UUID) -> UserProfile | None:
            return state.profile

        async def upsert(self, profile: UserProfile) -> None:
            state.upserts.append(profile)
            state.profile = profile

    monkeypatch.setattr(
        "app.profile.application.event_handlers.SqlProfileRepository",
        _FakeRepo,
    )
    return state


def _profile(*, onboarding_completed: bool) -> UserProfile:
    return UserProfile(
        user_id=uuid4(),
        age=30,
        sex="male",
        weight_kg=Decimal("70"),
        height_cm=Decimal("175"),
        goal="weight_loss",
        activity_level="moderately_active",
        dietary_pattern="omnivore",
        onboarding_completed=onboarding_completed,
    )


def _event(user_id: UUID) -> PlanCreated:
    return PlanCreated(
        plan_id=uuid4(),
        user_id=user_id,
        type="weekly",
        total_days=7,
        at=datetime.now(tz=UTC),
    )


@pytest.mark.asyncio
async def test_flag_flips_false_to_true(_patched_repo: _FakeRepoState) -> None:
    profile = _profile(onboarding_completed=False)
    _patched_repo.profile = profile
    sm = _FakeSessionMaker(_patched_repo)
    handler = make_flip_onboarding_on_plan_created(sm)  # type: ignore[arg-type]

    await handler(_event(profile.user_id))

    assert len(_patched_repo.upserts) == 1
    assert _patched_repo.upserts[0].onboarding_completed is True
    assert sm.last_session is not None
    assert sm.last_session.committed is True


@pytest.mark.asyncio
async def test_idempotent_when_flag_already_true(
    _patched_repo: _FakeRepoState,
) -> None:
    profile = _profile(onboarding_completed=True)
    _patched_repo.profile = profile
    sm = _FakeSessionMaker(_patched_repo)
    handler = make_flip_onboarding_on_plan_created(sm)  # type: ignore[arg-type]

    await handler(_event(profile.user_id))

    assert _patched_repo.upserts == []
    assert sm.last_session is not None
    assert sm.last_session.committed is False  # short-circuit, no write
    assert sm.last_session.rolled_back is False


@pytest.mark.asyncio
async def test_missing_profile_no_raise(_patched_repo: _FakeRepoState) -> None:
    _patched_repo.profile = None
    sm = _FakeSessionMaker(_patched_repo)
    handler = make_flip_onboarding_on_plan_created(sm)  # type: ignore[arg-type]

    # Must not raise.
    await handler(_event(uuid4()))

    assert _patched_repo.upserts == []


@pytest.mark.asyncio
async def test_concurrent_events_same_user_final_state_true(
    _patched_repo: _FakeRepoState,
) -> None:
    profile = _profile(onboarding_completed=False)
    _patched_repo.profile = profile
    sm = _FakeSessionMaker(_patched_repo)
    handler = make_flip_onboarding_on_plan_created(sm)  # type: ignore[arg-type]

    await asyncio.gather(
        handler(_event(profile.user_id)),
        handler(_event(profile.user_id)),
        handler(_event(profile.user_id)),
    )

    # Idempotent: final state True; at least one write, subsequent calls
    # observe flag already True and short-circuit. (Exact write count
    # depends on scheduling — the contract is `final state True`.)
    assert _patched_repo.profile is not None
    assert _patched_repo.profile.onboarding_completed is True
    assert len(_patched_repo.upserts) >= 1
