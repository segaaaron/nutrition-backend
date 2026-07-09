"""ADR-0026 L1 — 30-day region immutability check inside `UpdateProfile`.

Patrón #3 refactor: the use case no longer opens a nested
``session_scope()`` for the audit. It receives a ``RegionAuditPort``
adapter (bound to the SAME session as the profile upsert), so the
audit row and the profile row commit atomically. Tests now drive the
gate through an in-memory port stub.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from app.core.errors import BusinessRuleViolation, LockedError
from app.profile.application.use_cases import UpdateProfile
from app.profile.domain.entities import UserProfile

pytestmark = pytest.mark.anyio


@dataclass
class _StubRegionAudit:
    last_change: datetime | None = None
    insert_calls: list[dict] = field(default_factory=list)

    async def last_change_at(self, user_id: UUID) -> datetime | None:  # noqa: ARG002
        return self.last_change

    async def record_change(
        self,
        *,
        user_id: UUID,
        old_region: str | None,
        new_region: str | None,
        changed_at: datetime,
    ) -> None:
        self.insert_calls.append(
            {
                "uid": str(user_id),
                "old": old_region,
                "new": new_region,
                "ts": changed_at,
            }
        )


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


async def test_region_change_with_no_prior_audit_succeeds():
    profile = _build_profile("PE", "latam")
    repo = _StubProfilesRepo(profile)
    bus = _StubBus()
    audit = _StubRegionAudit(last_change=None)

    await UpdateProfile(profiles=repo, bus=bus, region_audit=audit)(
        user_id=profile.user_id, patch={"country": "ES"}
    )

    assert repo.upserted is not None
    assert repo.upserted.region == "eu"
    assert len(audit.insert_calls) == 1
    assert audit.insert_calls[0]["old"] == "latam"
    assert audit.insert_calls[0]["new"] == "eu"


async def test_region_change_inside_30d_raises_locked():
    profile = _build_profile("PE", "latam")
    repo = _StubProfilesRepo(profile)
    bus = _StubBus()
    audit = _StubRegionAudit(last_change=datetime.now(UTC) - timedelta(days=10))

    with pytest.raises(LockedError) as exc_info:
        await UpdateProfile(profiles=repo, bus=bus, region_audit=audit)(
            user_id=profile.user_id, patch={"country": "ES"}
        )

    err = exc_info.value
    assert err.detail == "region_change_locked"
    expected_s = int(timedelta(days=20).total_seconds())
    actual_s = int(err.extra["retry_after"])
    assert abs(actual_s - expected_s) <= 5
    assert audit.insert_calls == []


async def test_region_change_after_30d_succeeds():
    profile = _build_profile("PE", "latam")
    repo = _StubProfilesRepo(profile)
    bus = _StubBus()
    audit = _StubRegionAudit(last_change=datetime.now(UTC) - timedelta(days=31))

    await UpdateProfile(profiles=repo, bus=bus, region_audit=audit)(
        user_id=profile.user_id, patch={"country": "ES"}
    )
    assert len(audit.insert_calls) == 1


async def test_no_region_change_skips_audit():
    profile = _build_profile("PE", "latam")
    repo = _StubProfilesRepo(profile)
    bus = _StubBus()
    audit = _StubRegionAudit(last_change=None)

    await UpdateProfile(profiles=repo, bus=bus, region_audit=audit)(
        user_id=profile.user_id, patch={"country": "PE"}
    )
    assert audit.insert_calls == []


async def test_region_change_without_audit_port_refused():
    """Defensive contract: refusing a region change without the audit
    port is preferable to silently bypassing the 30-day lock + audit
    trail. Older call sites that forgot to wire the adapter must fail
    closed, not open.
    """
    profile = _build_profile("PE", "latam")
    repo = _StubProfilesRepo(profile)
    bus = _StubBus()

    with pytest.raises(BusinessRuleViolation) as exc_info:
        await UpdateProfile(profiles=repo, bus=bus, region_audit=None)(
            user_id=profile.user_id, patch={"country": "ES"}
        )
    assert "region_audit_unavailable" in str(exc_info.value)
