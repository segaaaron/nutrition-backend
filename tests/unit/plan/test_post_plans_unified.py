"""Contract tests for the unified ``POST /plans`` endpoint (2026-06-09).

After the architectural consolidation, ``POST /plans`` is the single
source of truth for plan generation. It serves two iOS contexts:

  1. **Onboarding final step.** Client sends ``{"profile": {...}}`` with
     the full :class:`OnboardingRequest`. The handler upserts the
     profile + computes goals atomically, then enqueues plan
     generation.
  2. **Regeneration from inside the app.** Client sends ``{}`` (body
     empty or just plan-shaping fields). The handler reads the existing
     profile; missing profile → 422 ``profile_not_found``.

Atomicity invariant: if profile save fails, NO plan job is enqueued.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.errors import register_exception_handlers
from app.core.problem_details import register_problem_handlers
from app.identity.presentation.dependencies import get_current_user, get_session
from app.plan.presentation import router as plan_router_module
from app.plan.presentation.router import router as plan_router
from app.profile.domain.entities import UserProfile

FAKE_USER_ID = UUID("22222222-2222-2222-2222-222222222222")
FAKE_PLAN_ID = UUID("33333333-3333-3333-3333-333333333333")
VALID_KEY = "550e8400-e29b-41d4-a716-446655440000"
VALID_KEY_2 = "550e8400-e29b-41d4-a716-446655440099"


def _profile_payload() -> dict[str, Any]:
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


class _FakeRedis:
    """In-memory Redis stand-in supporting the subset the idempotency
    helpers use (``get``/``set``)."""

    def __init__(self) -> None:
        self._kv: dict[str, str] = {}

    async def get(self, k: str) -> str | None:
        return self._kv.get(k)

    async def set(self, k: str, v: str, ex: int | None = None) -> bool:
        self._kv[k] = v
        return True


@pytest.fixture
def repo() -> _InMemRepo:
    return _InMemRepo()


@pytest.fixture
def enqueue_calls() -> list[dict[str, Any]]:
    return []


@pytest.fixture
def app(
    monkeypatch: pytest.MonkeyPatch,
    repo: _InMemRepo,
    enqueue_calls: list[dict[str, Any]],
) -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app)
    register_problem_handlers(app)
    app.include_router(plan_router)

    async def _override_session():
        yield None

    async def _override_user() -> UUID:
        return FAKE_USER_ID

    app.dependency_overrides[get_session] = _override_session
    app.dependency_overrides[get_current_user] = _override_user

    monkeypatch.setattr(plan_router_module, "SqlProfileRepository", lambda _s: repo)

    class _NoopComputeGoals:
        def __init__(self, *_a: Any, **_kw: Any) -> None: ...

        async def __call__(self, *, user_id: UUID) -> None:
            return None

    monkeypatch.setattr(plan_router_module, "InlineComputeGoals", _NoopComputeGoals)

    async def _fake_enqueue(**kwargs: Any) -> tuple[str, str]:
        # BE-7: enqueue_and_wait_plan returns (job_id, plan_id). A non-None
        # plan_id simulates the worker finishing within the wait → 200 "ready".
        # plan_id is a UUID string (CreatePlanResponse.plan_id is UUID-typed).
        enqueue_calls.append(kwargs)
        n = len(enqueue_calls)
        return f"arq-job-{n}", str(FAKE_PLAN_ID)

    monkeypatch.setattr(plan_router_module, "enqueue_and_wait_plan", _fake_enqueue)

    fake_redis = _FakeRedis()
    monkeypatch.setattr(plan_router_module, "get_redis", lambda: fake_redis)

    return app


@pytest.mark.asyncio
async def test_post_plans_with_profile_data_creates_profile_and_enqueues_plan(
    app: FastAPI, repo: _InMemRepo, enqueue_calls: list[dict[str, Any]]
) -> None:
    """Onboarding happy path: single POST persists profile + enqueues plan."""
    client = TestClient(app)
    resp = client.post(
        "/plans",
        json={"profile": _profile_payload()},
        headers={"Idempotency-Key": VALID_KEY},
    )

    # BE-7: worker finished within the wait → synchronous 200 "ready" + plan_id.
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "ready"
    assert body["job_id"] == "arq-job-1"
    assert body["plan_id"] == str(FAKE_PLAN_ID)
    assert body["plan_job"] == {"job_id": "arq-job-1", "status": "ready"}
    # Profile echoed back so iOS can render home without a second GET.
    assert body["profile"] is not None
    assert body["profile"]["user_id"] == str(FAKE_USER_ID)
    # Profile persisted.
    assert FAKE_USER_ID in repo.store
    # Enqueue happened exactly once with the user-derived job id.
    assert len(enqueue_calls) == 1
    assert enqueue_calls[0]["user_id"] == FAKE_USER_ID
    assert enqueue_calls[0]["plan_type"] == "week"
    assert enqueue_calls[0]["job_id"] == f"plan:{FAKE_USER_ID}:{VALID_KEY}"


@pytest.mark.asyncio
async def test_post_plans_without_profile_data_uses_existing_profile(
    app: FastAPI, repo: _InMemRepo, enqueue_calls: list[dict[str, Any]]
) -> None:
    """Regen path: empty body + existing profile → enqueues plan."""
    # Seed an existing profile in the repo.
    repo.store[FAKE_USER_ID] = UserProfile(user_id=FAKE_USER_ID)

    client = TestClient(app)
    resp = client.post(
        "/plans",
        json={},
        headers={"Idempotency-Key": VALID_KEY},
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "ready"
    assert body["job_id"] == "arq-job-1"
    # No profile echo because the client didn't send one.
    assert body["profile"] is None
    assert len(enqueue_calls) == 1


@pytest.mark.asyncio
async def test_post_plans_without_profile_data_and_no_profile_returns_422(
    app: FastAPI, enqueue_calls: list[dict[str, Any]]
) -> None:
    """Regen path with no existing profile → 422, no plan job."""
    client = TestClient(app)
    resp = client.post(
        "/plans",
        json={},
        headers={"Idempotency-Key": VALID_KEY},
    )

    assert resp.status_code == 422, resp.text
    # No plan job enqueued.
    assert enqueue_calls == []


@pytest.mark.asyncio
async def test_post_plans_atomic_profile_save_or_no_plan(
    app: FastAPI,
    repo: _InMemRepo,
    enqueue_calls: list[dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If profile save raises, NO plan job is enqueued.

    We simulate a failure inside the profile upsert path; the handler
    must propagate the error and skip the enqueue step entirely.
    """

    class _BrokenRepo(_InMemRepo):
        async def upsert(self, profile: UserProfile) -> None:
            raise RuntimeError("simulated_db_failure")

    broken = _BrokenRepo()
    monkeypatch.setattr(plan_router_module, "SqlProfileRepository", lambda _s: broken)

    client = TestClient(app, raise_server_exceptions=False)
    resp = client.post(
        "/plans",
        json={"profile": _profile_payload()},
        headers={"Idempotency-Key": VALID_KEY},
    )

    assert resp.status_code >= 500
    # Critical invariant: no enqueue.
    assert enqueue_calls == []


@pytest.mark.asyncio
async def test_post_plans_legacy_body_without_profile_still_works(
    app: FastAPI, repo: _InMemRepo, enqueue_calls: list[dict[str, Any]]
) -> None:
    """Backward-compat: legacy clients sending only ``{"type": "week"}``
    keep working when the profile already exists."""
    repo.store[FAKE_USER_ID] = UserProfile(user_id=FAKE_USER_ID)

    client = TestClient(app)
    resp = client.post(
        "/plans",
        json={"type": "week"},
        headers={"Idempotency-Key": VALID_KEY},
    )

    assert resp.status_code == 200, resp.text
    assert len(enqueue_calls) == 1
    assert enqueue_calls[0]["plan_type"] == "week"


@pytest.mark.asyncio
async def test_post_plans_idempotent_replay_returns_cached_body(
    app: FastAPI, repo: _InMemRepo, enqueue_calls: list[dict[str, Any]]
) -> None:
    """Same idempotency key + same body → second call returns the cached
    200 body without re-enqueueing."""
    repo.store[FAKE_USER_ID] = UserProfile(user_id=FAKE_USER_ID)

    client = TestClient(app)
    r1 = client.post(
        "/plans", json={}, headers={"Idempotency-Key": VALID_KEY}
    )
    r2 = client.post(
        "/plans", json={}, headers={"Idempotency-Key": VALID_KEY}
    )

    assert r1.status_code == 200
    assert r2.status_code == 200
    assert r1.json() == r2.json()
    # Only the first call hit the enqueuer.
    assert len(enqueue_calls) == 1
