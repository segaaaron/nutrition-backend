"""Router-level contract for `POST /me/onboarding`.

As of 2026-06-09, ``POST /me/onboarding`` is a **profile-only** save —
plan generation is owned exclusively by ``POST /plans`` (see
``tests/unit/plan/test_post_plans_unified.py``). These tests pin:

  - happy path → profile persisted, ``plan_job`` is ``None`` in the
    response (legacy field kept for backward-compat with iOS clients
    that already deserialise it).
  - re-call with same user → profile re-upserted (latest wins).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.errors import register_exception_handlers
from app.identity.presentation.dependencies import get_current_user, get_session
from app.profile.domain.entities import UserProfile
from app.profile.presentation import router as router_module
from app.profile.presentation.router import router


FAKE_USER_ID = UUID("11111111-1111-1111-1111-111111111111")


def _payload() -> dict[str, Any]:
    return {
        "age": 30,
        "sex": "male",
        "weight_kg": "72.0",
        "height_cm": "175",
        "goal": "weight_loss",
        "activity_level": "moderately_active",
        "dietary_pattern": "omnivore",
        "locale": "es",
    }


class _InMemRepo:
    def __init__(self) -> None:
        self.store: dict[UUID, UserProfile] = {}

    async def get(self, user_id: UUID) -> UserProfile | None:
        return self.store.get(user_id)

    async def upsert(self, profile: UserProfile) -> None:
        self.store[profile.user_id] = profile


@pytest.fixture
def repo() -> _InMemRepo:
    return _InMemRepo()


@pytest.fixture
def app(monkeypatch: pytest.MonkeyPatch, repo: _InMemRepo) -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(router)

    async def _override_session():
        yield None

    async def _override_user() -> UUID:
        return FAKE_USER_ID

    app.dependency_overrides[get_session] = _override_session
    app.dependency_overrides[get_current_user] = _override_user

    monkeypatch.setattr(router_module, "SqlProfileRepository", lambda _s: repo)

    class _NoopComputeGoals:
        def __init__(self, *_a: Any, **_kw: Any) -> None: ...

        async def __call__(self, *, user_id: UUID) -> None:
            return None

    monkeypatch.setattr(router_module, "InlineComputeGoals", _NoopComputeGoals)

    class _NoopRegionAudit:
        def __init__(self, *_a: Any, **_kw: Any) -> None: ...

    monkeypatch.setattr(router_module, "SqlRegionAudit", _NoopRegionAudit)

    return app


@pytest.mark.asyncio
async def test_onboarding_persists_profile_without_enqueuing_plan(
    app: FastAPI, repo: _InMemRepo
) -> None:
    client = TestClient(app)
    resp = client.post("/me/onboarding", json=_payload())

    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["user_id"] == str(FAKE_USER_ID)
    # Legacy field present, always None — plan enqueue lives in POST /plans.
    assert body["plan_job"] is None
    # Profile persisted.
    assert FAKE_USER_ID in repo.store


@pytest.mark.asyncio
async def test_onboarding_is_re_upsert_idempotent(
    app: FastAPI, repo: _InMemRepo
) -> None:
    client = TestClient(app)
    r1 = client.post("/me/onboarding", json=_payload())
    r2 = client.post("/me/onboarding", json={**_payload(), "weight_kg": "70.0"})

    assert r1.status_code == 201
    assert r2.status_code == 201
    # Both calls return plan_job=None and persist the latest profile state.
    assert r1.json()["plan_job"] is None
    assert r2.json()["plan_job"] is None
    assert repo.store[FAKE_USER_ID].weight_kg == Decimal("70.0")
