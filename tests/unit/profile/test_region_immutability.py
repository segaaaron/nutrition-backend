"""ADR-0026 L1 — 30-day region immutability check inside `UpdateProfile`.

We unit-test the gate by stubbing `session_scope` so no real DB is
required. The use case only reads/writes one well-known SQL pair
(`SELECT changed_at … LIMIT 1` then `INSERT … profile_region_change_audit`).
The stub session records calls and returns a controllable `changed_at`.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from app.core.errors import LockedError
from app.profile.application import use_cases as uc_mod
from app.profile.application.use_cases import UpdateProfile
from app.profile.domain.entities import UserProfile

pytestmark = pytest.mark.anyio


@dataclass
class _StubResult:
    value: object = None

    def scalar(self) -> object:
        return self.value


class _StubSession:
    def __init__(self, last_change: datetime | None) -> None:
        self.last_change = last_change
        self.insert_calls: list[dict] = []

    async def execute(self, stmt, params=None):  # noqa: ANN001
        sql = str(stmt).lower()
        if "select changed_at" in sql:
            return _StubResult(self.last_change)
        if "insert into profile_region_change_audit" in sql:
            self.insert_calls.append(params or {})
            return _StubResult(None)
        return _StubResult(None)


class _StubProfilesRepo:
    def __init__(self, profile: UserProfile) -> None:
        self.profile = profile
        self.upserted: UserProfile | None = None

    async def get(self, user_id):  # noqa: ANN001, ARG002
        return self.profile

    async def upsert(self, profile):  # noqa: ANN001
        self.upserted = profile


class _StubBus:
    def __init__(self) -> None:
        self.published: list = []

    async def publish(self, evt):  # noqa: ANN001
        self.published.append(evt)


def _build_profile(country: str, region: str) -> UserProfile:
    return UserProfile(
        user_id=uuid4(),
        age=30,
        sex="male",
        weight_kg=Decimal("70"),
        height_cm=Decimal("175"),
        goal="weight_loss",
        activity_level="moderately_active",
        country=country,
        region=region,
    )


@pytest.fixture(autouse=True)
def _disable_segment_gate(monkeypatch):
    # The segment gate has its own tests — neutralise it here.
    monkeypatch.setattr(uc_mod, "_enforce_mvp_segment_gate", lambda *_a, **_k: None)


def _patch_session(monkeypatch, stub: _StubSession) -> None:
    @asynccontextmanager
    async def _fake_scope():
        yield stub

    monkeypatch.setattr(uc_mod, "session_scope", _fake_scope)


async def test_region_change_with_no_prior_audit_succeeds(monkeypatch):
    profile = _build_profile("PE", "latam")
    repo = _StubProfilesRepo(profile)
    bus = _StubBus()
    stub = _StubSession(last_change=None)
    _patch_session(monkeypatch, stub)

    # Change country PE→ES (latam→eu)
    await UpdateProfile(profiles=repo, bus=bus)(
        user_id=profile.user_id, patch={"country": "ES"}
    )

    assert repo.upserted is not None
    assert repo.upserted.region == "eu"
    assert len(stub.insert_calls) == 1
    assert stub.insert_calls[0]["old"] == "latam"
    assert stub.insert_calls[0]["new"] == "eu"


async def test_region_change_inside_30d_raises_locked(monkeypatch):
    profile = _build_profile("PE", "latam")
    repo = _StubProfilesRepo(profile)
    bus = _StubBus()
    # Last change 10 days ago — inside the 30-day lock.
    stub = _StubSession(
        last_change=datetime.now(UTC) - timedelta(days=10)
    )
    _patch_session(monkeypatch, stub)

    with pytest.raises(LockedError) as exc_info:
        await UpdateProfile(profiles=repo, bus=bus)(
            user_id=profile.user_id, patch={"country": "ES"}
        )

    err = exc_info.value
    assert err.detail == "region_change_locked"
    # Retry-After should be within (30-10)d ± a few seconds.
    expected_s = int(timedelta(days=20).total_seconds())
    actual_s = int(err.extra["retry_after"])
    assert abs(actual_s - expected_s) <= 5
    # No INSERT happened.
    assert stub.insert_calls == []


async def test_region_change_after_30d_succeeds(monkeypatch):
    profile = _build_profile("PE", "latam")
    repo = _StubProfilesRepo(profile)
    bus = _StubBus()
    stub = _StubSession(
        last_change=datetime.now(UTC) - timedelta(days=31)
    )
    _patch_session(monkeypatch, stub)

    await UpdateProfile(profiles=repo, bus=bus)(
        user_id=profile.user_id, patch={"country": "ES"}
    )
    assert len(stub.insert_calls) == 1


async def test_no_region_change_skips_audit(monkeypatch):
    profile = _build_profile("PE", "latam")
    repo = _StubProfilesRepo(profile)
    bus = _StubBus()
    stub = _StubSession(last_change=None)
    _patch_session(monkeypatch, stub)

    # Patch with same country — region stays the same.
    await UpdateProfile(profiles=repo, bus=bus)(
        user_id=profile.user_id, patch={"country": "PE"}
    )
    assert stub.insert_calls == []
