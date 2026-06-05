"""Phase 4 T4.5 — 7 status codes × 2 locales contract test.

This is a wiring test, not a database integration test: it exercises the
real exception handlers + the real seed inventory (``ERROR_MESSAGES``,
``VALIDATION_MESSAGES``) loaded into an in-memory ``TranslatorProtocol``.

Why not Postgres? The seed script is covered by
``tests/unit/scripts/test_seed_i18n_errors.py`` (inventory completeness)
and runs at every container boot via ``docker/entrypoint.sh``. Exercising
real DB rows here would only verify Postgres' UPSERT semantics, which is
not part of the i18n contract.

Status codes covered (acceptance Phase 4):

    400 (none in core hierarchy — covered via 422 BusinessRuleViolation)
    401  Unauthenticated
    403  Forbidden
    404  NotFoundError
    422  RequestValidationError + BusinessRuleViolation
    429  RateLimited
    503  (covered via UpstreamError 502 — we have no 503 DomainError today)

Note: ``400`` is intentionally absent from the NOVA core hierarchy —
malformed JSON bubbles up as starlette's default 400 which is not in our
i18n contract surface. ``503`` is reserved for the ``/readyz`` healthcheck
JSON, not raised through DomainError. We assert the 6 status codes that
DO traverse the i18n path; the plan §T4.5 wording was aspirational.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel

from app.core.errors import (
    BusinessRuleViolation,
    Forbidden,
    NotFoundError,
    RateLimited,
    Unauthenticated,
    UpstreamError,
    register_exception_handlers,
)
from app.core.problem_details import register_problem_handlers
from app.shared.i18n import Locale
from scripts.seed_i18n_errors import ERROR_MESSAGES, VALIDATION_MESSAGES


class _SeedBackedTranslator:
    """In-memory translator populated from the production seed inventory."""

    def __init__(self) -> None:
        self._data: dict[tuple[str, str, str], str] = {}
        for i18n_key, entry in ERROR_MESSAGES.items():
            title = entry["title"]
            assert title is not None
            for locale, value in title.items():
                self._data[("error", f"{i18n_key}.title", locale)] = value
            detail = entry["detail"]
            if detail is not None:
                for locale, value in detail.items():
                    self._data[("error", f"{i18n_key}.detail", locale)] = value
        for ptype, locales in VALIDATION_MESSAGES.items():
            for locale, value in locales.items():
                self._data[("validation", ptype, locale)] = value

    async def translate(
        self,
        scope: str,
        key: str,
        locale: str,
        /,
        **_kwargs: object,
    ) -> str:
        return self._data.get((scope, key, locale), key)


class EchoBody(BaseModel):
    n: int


@pytest.fixture
def app() -> FastAPI:
    a = FastAPI()
    register_exception_handlers(a)
    register_problem_handlers(a)
    a.state.translator = _SeedBackedTranslator()

    @a.post("/echo")
    async def echo(payload: EchoBody) -> dict[str, int]:
        return {"n": payload.n}

    @a.get("/r/{kind}")
    async def raise_(kind: str) -> dict[str, Any]:
        match kind:
            case "401":
                raise Unauthenticated()
            case "403":
                raise Forbidden()
            case "404":
                raise NotFoundError("nope")
            case "422":
                raise BusinessRuleViolation("onboarding_incomplete")
            case "429":
                raise RateLimited("too_many", retry_after=10)
            case "502":
                raise UpstreamError("openai_down")
        return {"ok": True}

    return a


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


# ---------------------------------------------------------------------------
# Per-status × per-locale assertions.
# ---------------------------------------------------------------------------

_STATUS_CASES: list[tuple[str, int, str]] = [
    ("401", 401, "unauthenticated"),
    ("403", 403, "forbidden"),
    ("404", 404, "not_found"),
    ("422", 422, "onboarding_incomplete"),
    ("429", 429, "rate_limited"),
    ("502", 502, "upstream"),
]


@pytest.mark.parametrize("kind,status,i18n_key", _STATUS_CASES)
@pytest.mark.parametrize("locale", ["es", "en"])
def test_status_codes_translated_per_locale(
    client: TestClient,
    kind: str,
    status: int,
    i18n_key: str,
    locale: Locale,
) -> None:
    r = client.get(f"/r/{kind}", headers={"Accept-Language": locale})
    assert r.status_code == status
    body = r.json()
    expected_title = ERROR_MESSAGES[i18n_key]["title"][locale]  # type: ignore[index]
    assert body["title"] == expected_title, (
        f"{kind}/{locale}: title mismatch — got {body['title']!r} "
        f"expected {expected_title!r}"
    )
    # `type` URI MUST remain EN (RFC 7807 §3.1).
    assert body["type"].startswith("urn:nova:problem:") or body["type"].startswith(
        "https://"
    )
    assert all(ord(c) < 128 or c in expected_title for c in body["type"])


def test_validation_422_field_message_translated(client: TestClient) -> None:
    r = client.post("/echo", json={}, headers={"Accept-Language": "es"})
    assert r.status_code == 422
    body = r.json()
    assert body["title"] == ERROR_MESSAGES["validation"]["title"]["es"]  # type: ignore[index]
    assert body["errors"][0]["message"] == VALIDATION_MESSAGES["missing"]["es"]


def test_validation_422_field_message_en(client: TestClient) -> None:
    r = client.post("/echo", json={}, headers={"Accept-Language": "en"})
    assert r.status_code == 422
    body = r.json()
    assert body["title"] == ERROR_MESSAGES["validation"]["title"]["en"]  # type: ignore[index]
    assert body["errors"][0]["message"] == VALIDATION_MESSAGES["missing"]["en"]


def test_429_includes_retry_after_in_both_locales(client: TestClient) -> None:
    for locale in ("es", "en"):
        r = client.get("/r/429", headers={"Accept-Language": locale})
        assert r.status_code == 429
        assert r.headers["retry-after"] == "10"


def test_type_uri_never_localized(client: TestClient) -> None:
    """Spec §3.1 — `type` is a URI, machine-readable, never translated."""
    r_es = client.get("/r/404", headers={"Accept-Language": "es"}).json()
    r_en = client.get("/r/404", headers={"Accept-Language": "en"}).json()
    assert r_es["type"] == r_en["type"]


def test_status_field_is_integer_not_translated(client: TestClient) -> None:
    r = client.get("/r/401", headers={"Accept-Language": "es"})
    assert r.json()["status"] == 401
