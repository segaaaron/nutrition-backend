"""Unit tests for Phase 4 i18n wiring in RFC 7807 handlers.

The production lifespan binds a real Translator to ``app.state.translator``.
Here we substitute a deterministic in-memory fake (``TranslatorProtocol``)
that maps ``(scope, key, locale) -> str`` from a dict, so we can assert
the exact translation paths without DB/Redis.
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
from app.core.problem_details import (
    PROBLEM_CONTENT_TYPE,
    PROBLEM_URN_BASE,
    register_problem_handlers,
)


class _FakeTranslator:
    """In-memory ``TranslatorProtocol`` used to assert handler wiring.

    Stores ``{(scope, key, locale): value}``. On miss returns ``key`` (matches
    real Translator echo-on-miss contract).
    """

    def __init__(self, data: dict[tuple[str, str, str], str]) -> None:
        self._data = data
        self.calls: list[tuple[str, str, str]] = []

    async def translate(
        self,
        scope: str,
        key: str,
        locale: str,
        /,
        **_kwargs: object,
    ) -> str:
        self.calls.append((scope, key, locale))
        return self._data.get((scope, key, locale), key)


class EchoBody(BaseModel):
    n: int


def _build_app(translator: _FakeTranslator | None) -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app)
    register_problem_handlers(app)
    if translator is not None:
        app.state.translator = translator

    @app.post("/echo")
    async def echo(payload: EchoBody) -> dict[str, int]:
        return {"n": payload.n}

    @app.get("/raise/{kind}")
    async def raise_(kind: str) -> dict[str, Any]:
        if kind == "bru":
            raise BusinessRuleViolation("onboarding_incomplete")
        if kind == "nf":
            raise NotFoundError("recipe_42")
        if kind == "unauth":
            raise Unauthenticated()
        if kind == "forbidden":
            raise Forbidden()
        if kind == "ratelimit":
            raise RateLimited("too_many", retry_after=30)
        if kind == "upstream":
            raise UpstreamError("openai_timeout")
        return {"ok": True}

    return app


# ---------------------------------------------------------------------------
# Header-only locale resolution (no profile DB lookup on error path).
# ---------------------------------------------------------------------------


def test_business_rule_translates_title_when_locale_es() -> None:
    tr = _FakeTranslator(
        {
            ("error", "onboarding_incomplete.title", "es"): "Onboarding incompleto",
            ("error", "onboarding_incomplete.detail", "es"): "Completa tu perfil.",
        }
    )
    client = TestClient(_build_app(tr))
    r = client.get("/raise/bru", headers={"Accept-Language": "es-ES,es;q=0.9"})
    assert r.status_code == 422
    body = r.json()
    assert body["title"] == "Onboarding incompleto"
    assert body["detail"] == "Completa tu perfil."
    assert body["type"] == f"{PROBLEM_URN_BASE}:plan:onboarding-incomplete"


def test_business_rule_falls_back_to_en_when_locale_en() -> None:
    tr = _FakeTranslator({})  # all misses
    client = TestClient(_build_app(tr))
    r = client.get("/raise/bru", headers={"Accept-Language": "en-US"})
    assert r.status_code == 422
    body = r.json()
    # Echo-on-miss → handler reverts to canonical EN strings.
    assert body["title"] == "Onboarding incomplete"
    assert body["detail"] == "onboarding_incomplete"


def test_not_found_translates_title() -> None:
    tr = _FakeTranslator(
        {("error", "not_found.title", "es"): "Recurso no encontrado"}
    )
    client = TestClient(_build_app(tr))
    r = client.get("/raise/nf", headers={"Accept-Language": "es"})
    body = r.json()
    assert body["title"] == "Recurso no encontrado"


def test_unauthenticated_translates_401() -> None:
    tr = _FakeTranslator(
        {
            ("error", "unauthenticated.title", "es"): "Autenticación requerida",
            ("error", "unauthenticated.detail", "es"): "Token faltante o inválido.",
        }
    )
    client = TestClient(_build_app(tr))
    r = client.get("/raise/unauth", headers={"Accept-Language": "es"})
    assert r.status_code == 401
    body = r.json()
    assert body["title"] == "Autenticación requerida"
    assert body["detail"] == "Token faltante o inválido."


def test_forbidden_translates_403() -> None:
    tr = _FakeTranslator(
        {("error", "forbidden.title", "es"): "Acceso denegado"}
    )
    client = TestClient(_build_app(tr))
    r = client.get("/raise/forbidden", headers={"Accept-Language": "es"})
    assert r.status_code == 403
    assert r.json()["title"] == "Acceso denegado"


def test_rate_limited_includes_retry_after_header() -> None:
    tr = _FakeTranslator(
        {("error", "rate_limited.title", "es"): "Límite de peticiones excedido"}
    )
    client = TestClient(_build_app(tr))
    r = client.get("/raise/ratelimit", headers={"Accept-Language": "es"})
    assert r.status_code == 429
    assert r.headers["retry-after"] == "30"
    assert r.json()["title"] == "Límite de peticiones excedido"


def test_upstream_502_translates() -> None:
    tr = _FakeTranslator(
        {("error", "upstream.title", "es"): "Error de servicio externo"}
    )
    client = TestClient(_build_app(tr))
    r = client.get("/raise/upstream", headers={"Accept-Language": "es"})
    assert r.status_code == 502
    assert r.json()["title"] == "Error de servicio externo"


def test_no_translator_attribute_falls_back_to_en() -> None:
    """Bare app without lifespan must not crash — must echo EN."""
    client = TestClient(_build_app(translator=None))
    r = client.get("/raise/bru", headers={"Accept-Language": "es"})
    assert r.status_code == 422
    assert r.json()["title"] == "Onboarding incomplete"


def test_type_uri_is_never_translated() -> None:
    """RFC 7807 §3.1 — `type` URI is a stable machine identifier."""
    tr = _FakeTranslator(
        {
            ("error", "onboarding_incomplete.title", "es"): "Onboarding incompleto",
            # malicious seed — would never happen but verify defence in depth
            (
                "error",
                "plan:onboarding-incomplete",
                "es",
            ): "https://evil.example/oops",
        }
    )
    client = TestClient(_build_app(tr))
    r = client.get("/raise/bru", headers={"Accept-Language": "es"})
    body = r.json()
    assert body["type"] == f"{PROBLEM_URN_BASE}:plan:onboarding-incomplete"


def test_validation_error_translates_envelope_and_messages() -> None:
    tr = _FakeTranslator(
        {
            ("error", "validation.title", "es"): "Error de validación",
            (
                "error",
                "validation.detail",
                "es",
            ): "Uno o más campos no superaron la validación.",
            ("validation", "missing", "es"): "Este campo es obligatorio.",
        }
    )
    client = TestClient(_build_app(tr))
    r = client.post("/echo", json={}, headers={"Accept-Language": "es"})
    assert r.status_code == 422
    body = r.json()
    assert body["title"] == "Error de validación"
    assert body["detail"] == "Uno o más campos no superaron la validación."
    assert body["errors"]
    assert body["errors"][0]["message"] == "Este campo es obligatorio."


def test_no_accept_language_defaults_to_es() -> None:
    tr = _FakeTranslator(
        {("error", "onboarding_incomplete.title", "es"): "Onboarding incompleto"}
    )
    client = TestClient(_build_app(tr))
    r = client.get("/raise/bru")  # no Accept-Language
    body = r.json()
    assert body["title"] == "Onboarding incompleto"


def test_unsupported_locale_in_header_falls_back_to_es() -> None:
    tr = _FakeTranslator(
        {("error", "onboarding_incomplete.title", "es"): "Onboarding incompleto"}
    )
    client = TestClient(_build_app(tr))
    r = client.get("/raise/bru", headers={"Accept-Language": "pt-BR"})
    body = r.json()
    # pt-BR not supported → fallback to D4 ES default.
    assert body["title"] == "Onboarding incompleto"


def test_content_type_remains_problem_json_under_i18n() -> None:
    tr = _FakeTranslator({})
    client = TestClient(_build_app(tr))
    r = client.get("/raise/bru", headers={"Accept-Language": "en"})
    assert r.headers["content-type"].startswith(PROBLEM_CONTENT_TYPE)


@pytest.mark.parametrize("status_kind,expected_status", [
    ("bru", 422),
    ("nf", 404),
    ("unauth", 401),
    ("forbidden", 403),
    ("ratelimit", 429),
    ("upstream", 502),
])
def test_status_code_unaffected_by_translation(
    status_kind: str, expected_status: int
) -> None:
    tr = _FakeTranslator({})  # all misses
    client = TestClient(_build_app(tr))
    r = client.get(f"/raise/{status_kind}", headers={"Accept-Language": "es"})
    assert r.status_code == expected_status
