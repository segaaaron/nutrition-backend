"""Contract tests for `app.vision.presentation.router`.

Strategy
--------
The full ``create_app()`` factory pulls in DB engine / Redis / Arq, which
are out of scope for unit tests. We instead build a *minimal* FastAPI app
that mounts the vision router, registers the same exception handlers used
in production, and overrides the dependencies that bridge to infrastructure:

- ``get_current_user`` → returns a deterministic UUID (auth boundary).
- ``get_session`` → returns ``None`` (router never touches it; use cases
  are patched module-wide).
- Module-level helpers (``_check_rate_limit``, ``_enqueue``) plus the
  use-case classes (``SubmitPhoto``, ``GetJobStatus``, ``LearnUserCorrection``)
  and the ``assert_owns`` BOLA guard are monkey-patched on the router
  module so behaviour can be steered per-test without spinning up infra.

This isolates the router itself (URL shape, status code mapping, header
echo, request parsing, response shape) from every collaborator it owns.
"""

from __future__ import annotations

import sys
import types
from unittest.mock import AsyncMock, MagicMock

# --- pyvips stub ---------------------------------------------------------- #
# The vision router imports ``app.imaging.infrastructure.vips_compressor``
# at module load, which requires the native ``libvips`` library. CI dev
# laptops don't always have it installed, and this is a router-only unit
# test — the compressor is patched away per test. Inject a minimal stub so
# the import chain resolves.
if "pyvips" not in sys.modules:
    _pyvips_stub = types.ModuleType("pyvips")
    _pyvips_stub.Image = type("Image", (), {})  # type: ignore[attr-defined]
    sys.modules["pyvips"] = _pyvips_stub

from datetime import UTC, datetime  # noqa: E402
from typing import Any  # noqa: E402
from uuid import UUID, uuid4  # noqa: E402

import pytest  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.core.errors import (  # noqa: E402
    Forbidden,
    NotFoundError,
    RateLimited,
    Unauthenticated,
    ValidationError,
    register_exception_handlers,
)
from app.identity.presentation.dependencies import get_current_user, get_session  # noqa: E402
from app.vision.domain.entities import DetectedFoodItem, VisionJob  # noqa: E402
from app.vision.presentation import router as router_module  # noqa: E402
from app.vision.presentation.router import router  # noqa: E402

# --------------------------------------------------------------------------- #
# Fixtures                                                                    #
# --------------------------------------------------------------------------- #


FAKE_USER_ID = UUID("11111111-1111-1111-1111-111111111111")


def _build_test_app(authenticated: bool = True) -> FastAPI:
    """Minimal FastAPI app mounting the vision router with overrides."""
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(router)

    async def _override_session():
        session = AsyncMock()
        _exec_result = MagicMock()
        _exec_result.first.return_value = None
        session.execute.return_value = _exec_result
        yield session

    async def _override_user_authed() -> UUID:
        return FAKE_USER_ID

    async def _override_user_anon() -> UUID:
        raise Unauthenticated("missing_bearer")

    app.dependency_overrides[get_session] = _override_session
    app.dependency_overrides[get_current_user] = (
        _override_user_authed if authenticated else _override_user_anon
    )
    return app


@pytest.fixture
def app_authed() -> FastAPI:
    return _build_test_app(authenticated=True)


@pytest.fixture
def app_anon() -> FastAPI:
    return _build_test_app(authenticated=False)


@pytest.fixture
def client(app_authed: FastAPI) -> TestClient:
    return TestClient(app_authed)


@pytest.fixture
def anon_client(app_anon: FastAPI) -> TestClient:
    return TestClient(app_anon)


# --------------------------------------------------------------------------- #
# Helpers                                                                     #
# --------------------------------------------------------------------------- #


def _jpeg_bytes(size: int = 64) -> bytes:
    """Minimal JPEG-like payload — content sniffing is patched away via
    the SubmitPhoto fake, so any non-empty bytes suffice."""
    return b"\xff\xd8\xff" + b"\x00" * (size - 3)


def _multipart_image(content: bytes = b"", mime: str = "image/jpeg") -> dict[str, Any]:
    return {"image": ("meal.jpg", content or _jpeg_bytes(), mime)}


def _patch_submit(monkeypatch: pytest.MonkeyPatch, behaviour):
    """Replace ``SubmitPhoto`` with a stub whose call returns ``behaviour``
    (or raises if behaviour is an Exception)."""
    captured: dict[str, Any] = {}

    class _Fake:
        def __init__(self, *_, **__):
            pass

        async def __call__(self, **kwargs):
            captured.update(kwargs)
            if isinstance(behaviour, Exception):
                raise behaviour
            return behaviour

    monkeypatch.setattr(router_module, "SubmitPhoto", _Fake)
    # Neutralise infra constructors (the router builds them eagerly,
    # before the fake __call__ runs).
    monkeypatch.setattr(router_module, "SqlVisionJobRepository", lambda *_: object())
    monkeypatch.setattr(router_module, "VipsImageCompressor", lambda: object())
    monkeypatch.setattr(router_module, "OpenAIVisionProvider", lambda: object())
    monkeypatch.setattr(router_module, "get_event_bus", lambda: object())

    async def _noop_rate_limit(_user_id: UUID, *, persist: bool = True) -> None:
        return None

    monkeypatch.setattr(router_module, "_check_rate_limit", _noop_rate_limit)
    return captured


def _patch_get_job_status(monkeypatch: pytest.MonkeyPatch, behaviour):
    class _Fake:
        def __init__(self, *_, **__):
            pass

        async def __call__(self, **_kwargs):
            if isinstance(behaviour, Exception):
                raise behaviour
            return behaviour

    monkeypatch.setattr(router_module, "GetJobStatus", _Fake)
    monkeypatch.setattr(router_module, "SqlVisionJobRepository", lambda *_: object())


def _patch_learn(monkeypatch: pytest.MonkeyPatch, *, raises: Exception | None = None):
    captured: dict[str, Any] = {}

    class _Fake:
        def __init__(self, *_, **__):
            pass

        async def __call__(self, **kwargs):
            captured.update(kwargs)
            if raises is not None:
                raise raises

    monkeypatch.setattr(router_module, "LearnUserCorrection", _Fake)
    return captured


def _patch_assert_owns(monkeypatch: pytest.MonkeyPatch, *, raises: Exception | None = None):
    captured: dict[str, Any] = {}

    async def _fake(_session, **kwargs):
        captured.update(kwargs)
        if raises is not None:
            raise raises

    monkeypatch.setattr(router_module, "assert_owns", _fake)
    return captured


# =========================================================================== #
# POST /logs/food/photo                                                       #
# =========================================================================== #


class TestSubmitFoodPhoto:
    def test_returns_202_with_job_id_when_authed_and_idempotent(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        job_id = uuid4()
        captured = _patch_submit(monkeypatch, behaviour=job_id)

        resp = client.post(
            "/logs/food/photo",
            files=_multipart_image(),
            data={"meal_time": "lunch", "locale": "en", "region": "us"},
            headers={"Idempotency-Key": "abc123"},
        )

        assert resp.status_code == 202
        body = resp.json()
        assert body == {"job_id": str(job_id), "status": "queued"}
        assert captured["user_id"] == FAKE_USER_ID
        assert captured["meal_time"] == "lunch"
        assert captured["idempotency_key"] == "abc123"
        assert captured["locale"] == "en"
        assert captured["region"] == "us"

    def test_returns_422_when_idempotency_key_header_missing(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_submit(monkeypatch, behaviour=uuid4())

        resp = client.post(
            "/logs/food/photo",
            files=_multipart_image(),
            data={"meal_time": "lunch"},
        )

        assert resp.status_code == 422
        body = resp.json()
        assert body["detail"] == "idempotency_key_required"
        assert body["title"] == "Validation failed"

    def test_returns_401_when_no_bearer_token(
        self, anon_client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_submit(monkeypatch, behaviour=uuid4())

        resp = anon_client.post(
            "/logs/food/photo",
            files=_multipart_image(),
            headers={"Idempotency-Key": "abc"},
        )

        assert resp.status_code == 401
        assert resp.json()["detail"] == "missing_bearer"

    def test_returns_422_when_use_case_reports_unsupported_mime(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_submit(monkeypatch, behaviour=ValidationError("unsupported_mime:text/plain"))

        resp = client.post(
            "/logs/food/photo",
            files=_multipart_image(),
            headers={"Idempotency-Key": "abc"},
        )

        assert resp.status_code == 422
        assert resp.json()["detail"] == "unsupported_mime:text/plain"

    def test_returns_422_when_use_case_reports_image_too_large(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_submit(monkeypatch, behaviour=ValidationError("upload_too_large:9000000"))

        resp = client.post(
            "/logs/food/photo",
            files=_multipart_image(),
            headers={"Idempotency-Key": "abc"},
        )

        assert resp.status_code == 422
        assert resp.json()["detail"].startswith("upload_too_large:")

    def test_returns_422_when_prefilter_rejects_non_food(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_submit(monkeypatch, behaviour=ValidationError("not_food_image:supplement"))

        resp = client.post(
            "/logs/food/photo",
            files=_multipart_image(),
            headers={"Idempotency-Key": "abc"},
        )

        assert resp.status_code == 422
        assert resp.json()["detail"] == "not_food_image:supplement"

    def test_returns_429_when_rate_limit_exceeded(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_submit(monkeypatch, behaviour=uuid4())

        async def _raise(_uid: UUID, *, persist: bool = True) -> None:
            raise RateLimited("rate_limit_exceeded", retry_after=42)

        monkeypatch.setattr(router_module, "_check_rate_limit", _raise)

        resp = client.post(
            "/logs/food/photo",
            files=_multipart_image(),
            headers={"Idempotency-Key": "abc"},
        )

        assert resp.status_code == 429
        body = resp.json()
        assert body["detail"] == "rate_limit_exceeded"
        # RateLimited carries the retry_after as an extra → surfaced in body.
        assert body["retry_after"] == 42
        # RFC 6585 §4: Retry-After header echoed for HTTP-level consumers.
        assert resp.headers["Retry-After"] == "42"

    def test_idempotency_key_is_forwarded_to_use_case(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        job_id = uuid4()
        captured = _patch_submit(monkeypatch, behaviour=job_id)

        client.post(
            "/logs/food/photo",
            files=_multipart_image(),
            data={"meal_time": "breakfast"},
            headers={"Idempotency-Key": "client-supplied-key"},
        )

        assert captured["idempotency_key"] == "client-supplied-key"
        assert captured["meal_time"] == "breakfast"

    def test_invalid_meal_time_returns_422(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_submit(monkeypatch, behaviour=uuid4())

        resp = client.post(
            "/logs/food/photo",
            files=_multipart_image(),
            data={"meal_time": "second_breakfast"},  # not in Literal
            headers={"Idempotency-Key": "abc"},
        )

        assert resp.status_code == 422


# =========================================================================== #
# POST /ai/recognize (deprecated alias)                                       #
# =========================================================================== #


class TestAiRecognizeAlias:
    def test_alias_delegates_to_submit_with_default_locale_region(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        job_id = uuid4()
        captured = _patch_submit(monkeypatch, behaviour=job_id)

        resp = client.post(
            "/ai/recognize",
            files=_multipart_image(),
            data={"meal_time": "dinner"},
            headers={"Idempotency-Key": "legacy"},
        )

        assert resp.status_code == 202
        assert resp.json()["job_id"] == str(job_id)
        assert captured["locale"] == "en"
        assert captured["region"] == "us"
        assert captured["meal_time"] == "dinner"


# =========================================================================== #
# GET /logs/food/jobs/{job_id}                                                #
# =========================================================================== #


def _completed_job(user_id: UUID) -> VisionJob:
    return VisionJob(
        id=uuid4(),
        user_id=user_id,
        status="completed",
        image_sha256="a" * 64,
        created_at=datetime.now(UTC),
        completed_at=datetime.now(UTC),
        detected_items=[
            DetectedFoodItem(
                name="oatmeal",
                estimated_amount_g=__import__("decimal").Decimal("120"),
                kcal=180,
                protein_g=6,
                carbs_g=30,
                fat_g=3,
                confidence=0.92,
                matched_food_id=uuid4(),
                match_method="trigram",
            ),
        ],
    )


class TestGetJobStatus:
    def test_returns_200_with_detected_items_for_owner(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        job = _completed_job(FAKE_USER_ID)
        _patch_get_job_status(monkeypatch, behaviour=job)

        resp = client.get(f"/logs/food/jobs/{job.id}")

        assert resp.status_code == 200
        body = resp.json()
        assert body["job_id"] == str(job.id)
        assert body["status"] == "completed"
        assert len(body["items"]) == 1
        item = body["items"][0]
        assert item["name"] == "oatmeal"
        assert item["kcal"] == 180
        assert item["match_method"] == "trigram"

    def test_returns_404_when_job_unknown(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_get_job_status(monkeypatch, behaviour=NotFoundError(f"vision_job:{uuid4()}"))

        resp = client.get(f"/logs/food/jobs/{uuid4()}")

        assert resp.status_code == 404
        assert resp.json()["detail"].startswith("vision_job:")

    def test_returns_403_when_job_owned_by_other_user(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_get_job_status(monkeypatch, behaviour=Forbidden("not_owner"))

        resp = client.get(f"/logs/food/jobs/{uuid4()}")

        assert resp.status_code == 403
        assert resp.json()["detail"] == "not_owner"

    def test_returns_401_when_unauthenticated(self, anon_client: TestClient) -> None:
        resp = anon_client.get(f"/logs/food/jobs/{uuid4()}")
        assert resp.status_code == 401

    def test_returns_422_when_job_id_not_uuid(self, client: TestClient) -> None:
        resp = client.get("/logs/food/jobs/not-a-uuid")
        assert resp.status_code == 422

    def test_serialises_empty_items_when_job_still_queued(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        job = VisionJob(
            id=uuid4(),
            user_id=FAKE_USER_ID,
            status="queued",
            image_sha256="b" * 64,
            created_at=datetime.now(UTC),
        )
        _patch_get_job_status(monkeypatch, behaviour=job)

        resp = client.get(f"/logs/food/jobs/{job.id}")

        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "queued"
        assert body["items"] == []
        assert body["error_code"] is None
        assert body["completed_at"] is None

    # ------------------------------------------------------------------ #
    # Plate explanation (groups / total_kcal / summary)                   #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _grouped_job() -> VisionJob:
        from decimal import Decimal as _D

        def _it(name: str, kcal: int, group: str) -> DetectedFoodItem:
            return DetectedFoodItem(
                name=name,
                estimated_amount_g=_D("100"),
                kcal=kcal,
                protein_g=0,
                carbs_g=0,
                fat_g=0,
                confidence=0.9,
                food_group=group,  # type: ignore[arg-type]
            )

        return VisionJob(
            id=uuid4(),
            user_id=FAKE_USER_ID,
            status="completed",
            image_sha256="c" * 64,
            created_at=datetime.now(UTC),
            completed_at=datetime.now(UTC),
            detected_items=[
                _it("pollo", 198, "protein"),
                _it("tomate", 7, "vegetable"),
                _it("cebolla", 12, "vegetable"),
            ],
        )

    def test_completed_job_includes_plate_explanation_default_es(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        job = self._grouped_job()
        _patch_get_job_status(monkeypatch, behaviour=job)

        resp = client.get(f"/logs/food/jobs/{job.id}")

        assert resp.status_code == 200
        body = resp.json()
        assert body["total_kcal"] == 217
        assert [g["group"] for g in body["groups"]] == ["protein", "vegetable"]
        veg = body["groups"][1]
        assert veg["item_names"] == ["tomate", "cebolla"]
        assert veg["total_kcal"] == 19
        # Prose `summary` was removed (owner 2026-07-10) — detail lives in
        # items[]/groups[]. The localized group label carries the language.
        assert body["groups"][0]["label"] == "proteína"
        assert "summary" not in body
        assert body["items"][0]["food_group"] == "protein"

    def test_accept_language_en_switches_group_label_language(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        job = self._grouped_job()
        _patch_get_job_status(monkeypatch, behaviour=job)

        resp = client.get(
            f"/logs/food/jobs/{job.id}", headers={"Accept-Language": "en-US,en;q=0.9"}
        )

        assert resp.status_code == 200
        assert resp.json()["groups"][0]["label"] == "protein"

    def test_queued_job_has_no_plate_explanation(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        job = VisionJob(
            id=uuid4(),
            user_id=FAKE_USER_ID,
            status="queued",
            image_sha256="d" * 64,
            created_at=datetime.now(UTC),
        )
        _patch_get_job_status(monkeypatch, behaviour=job)

        body = client.get(f"/logs/food/jobs/{job.id}").json()

        assert body["groups"] == []
        assert body["total_kcal"] is None
        assert "summary" not in body

    def test_explainer_failure_degrades_without_breaking_poll(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        job = self._grouped_job()
        _patch_get_job_status(monkeypatch, behaviour=job)

        def _boom(*_a, **_kw):
            raise RuntimeError("explainer bug")

        monkeypatch.setattr(router_module, "explain_plate", _boom)

        resp = client.get(f"/logs/food/jobs/{job.id}")

        assert resp.status_code == 200
        body = resp.json()
        assert len(body["items"]) == 3  # items still served
        assert body["groups"] == []
        assert "summary" not in body


# =========================================================================== #
# POST /logs/food/{food_log_id}/edit                                          #
# =========================================================================== #


class TestEditFoodLog:
    def test_returns_204_on_successful_correction(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        owns_capture = _patch_assert_owns(monkeypatch)
        learn_capture = _patch_learn(monkeypatch)

        food_log_id = uuid4()
        corrected_food_id = uuid4()
        resp = client.post(
            f"/logs/food/{food_log_id}/edit",
            json={
                "detected_name": "OAT MEAL ",
                "corrected_food_id": str(corrected_food_id),
                "corrected_amount_g": "150.0",
            },
        )

        assert resp.status_code == 204
        assert resp.content == b""
        # BOLA guard invoked with the path id + JWT user.
        assert owns_capture["table"] == "food_logs"
        assert owns_capture["resource_id"] == food_log_id
        assert owns_capture["user_id"] == FAKE_USER_ID
        # Use case received the body fields verbatim.
        assert learn_capture["detected_name"] == "OAT MEAL "
        assert learn_capture["corrected_food_id"] == corrected_food_id

    def test_returns_403_when_food_log_owned_by_other_user(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_assert_owns(monkeypatch, raises=Forbidden("not_owner"))
        _patch_learn(monkeypatch)

        resp = client.post(
            f"/logs/food/{uuid4()}/edit",
            json={"detected_name": "rice"},
        )

        assert resp.status_code == 403
        assert resp.json()["detail"] == "not_owner"

    def test_returns_404_when_food_log_does_not_exist(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_assert_owns(monkeypatch, raises=NotFoundError("food_logs_not_found"))
        _patch_learn(monkeypatch)

        resp = client.post(
            f"/logs/food/{uuid4()}/edit",
            json={"detected_name": "rice"},
        )

        assert resp.status_code == 404
        assert resp.json()["detail"] == "food_logs_not_found"

    def test_returns_422_when_detected_name_missing(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_assert_owns(monkeypatch)
        _patch_learn(monkeypatch)

        resp = client.post(
            f"/logs/food/{uuid4()}/edit",
            json={"corrected_food_id": str(uuid4())},
        )

        assert resp.status_code == 422

    def test_returns_422_when_extra_field_passed(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # EditDetectedItemRequest has extra='forbid' — defends against
        # mass-assignment style attacks.
        _patch_assert_owns(monkeypatch)
        _patch_learn(monkeypatch)

        resp = client.post(
            f"/logs/food/{uuid4()}/edit",
            json={"detected_name": "rice", "is_admin": True},
        )

        assert resp.status_code == 422

    def test_returns_401_when_unauthenticated(self, anon_client: TestClient) -> None:
        resp = anon_client.post(
            f"/logs/food/{uuid4()}/edit",
            json={"detected_name": "rice"},
        )
        assert resp.status_code == 401
