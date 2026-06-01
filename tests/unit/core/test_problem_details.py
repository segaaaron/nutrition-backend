"""RFC 7807 problem-details middleware contract tests.

A minimal FastAPI app is constructed per test — we do *not* spin up the
real `create_app()` factory because it requires DB/Redis. The handlers
are pure functions of the exception + request, so an isolated app
exercises every path."""
from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel

from app.core.errors import BusinessRuleViolation, NotFoundError
from app.core.problem_details import (
    PROBLEM_CONTENT_TYPE,
    PROBLEM_URN_BASE,
    ProblemDetails,
    register_problem_handlers,
)


class EchoBody(BaseModel):
    n: int


def _build_app() -> FastAPI:
    app = FastAPI()
    register_problem_handlers(app)

    @app.post("/echo")
    async def echo(payload: EchoBody) -> dict[str, int]:
        return {"n": payload.n}

    @app.get("/raise/{kind}/{detail}")
    async def raise_(kind: str, detail: str) -> dict[str, Any]:
        if kind == "bru":
            raise BusinessRuleViolation(detail)
        if kind == "nf":
            raise NotFoundError(detail)
        if kind == "pd":
            raise ProblemDetails(
                type=f"{PROBLEM_URN_BASE}:test:custom",
                title="Custom",
                status=418,
                detail=detail,
                extras={"hint": "teapot"},
            )
        return {"ok": True}

    return app


@pytest.fixture
def client() -> TestClient:
    return TestClient(_build_app())


def test_business_rule_segment_unsupported_returns_urn_with_segment_extra(
    client: TestClient,
) -> None:
    r = client.get("/raise/bru/segment_unsupported_mvp:pediatric")
    assert r.status_code == 422
    assert r.headers["content-type"].startswith(PROBLEM_CONTENT_TYPE)
    body = r.json()
    assert body["type"] == f"{PROBLEM_URN_BASE}:plan:segment-unsupported-mvp"
    assert body["title"] == "User segment not supported in MVP"
    assert body["status"] == 422
    assert body["detail"] == "segment_unsupported_mvp:pediatric"
    assert body["segment"] == "pediatric"
    assert body["instance"] == "/raise/bru/segment_unsupported_mvp:pediatric"


@pytest.mark.parametrize(
    "detail,suffix",
    [
        ("allergen_unmapped_requires_review", "plan:allergen-unmapped-requires-review"),
        ("trimester_required_for_pregnancy", "plan:trimester-required-for-pregnancy"),
        (
            "breastfeeding_status_required_for_lactation",
            "plan:breastfeeding-status-required-for-lactation",
        ),
        ("height_required", "plan:height-required"),
        ("onboarding_incomplete", "plan:onboarding-incomplete"),
        ("pediatric_outside_mvp_scope", "plan:pediatric-outside-mvp-scope"),
        ("geriatric_requires_clinical_review", "plan:geriatric-requires-clinical-review"),
    ],
)
def test_business_rule_known_details_map_to_urn(
    client: TestClient, detail: str, suffix: str
) -> None:
    r = client.get(f"/raise/bru/{detail}")
    assert r.status_code == 422
    body = r.json()
    assert body["type"] == f"{PROBLEM_URN_BASE}:{suffix}"
    assert body["detail"] == detail


def test_business_rule_profile_missing_extracts_field(client: TestClient) -> None:
    r = client.get("/raise/bru/profile_missing:height_cm")
    body = r.json()
    assert body["type"] == f"{PROBLEM_URN_BASE}:plan:profile-missing"
    assert body["field"] == "height_cm"


def test_business_rule_unknown_detail_falls_back_to_generic(client: TestClient) -> None:
    r = client.get("/raise/bru/some_unrecognised_rule")
    assert r.status_code == 422
    body = r.json()
    assert body["type"] == f"{PROBLEM_URN_BASE}:business-rule"
    assert body["title"] == "Business rule violation"


def test_not_found_returns_resource_not_found_urn(client: TestClient) -> None:
    r = client.get("/raise/nf/recipe_42")
    assert r.status_code == 404
    assert r.headers["content-type"].startswith(PROBLEM_CONTENT_TYPE)
    body = r.json()
    assert body["type"] == f"{PROBLEM_URN_BASE}:resource:not-found"
    assert body["title"] == "Resource not found"
    assert body["detail"] == "recipe_42"


def test_pydantic_validation_error_returns_field_errors(client: TestClient) -> None:
    r = client.post("/echo", json={})  # missing required field `n`
    assert r.status_code == 422
    assert r.headers["content-type"].startswith(PROBLEM_CONTENT_TYPE)
    body = r.json()
    assert body["type"] == f"{PROBLEM_URN_BASE}:validation:invalid-field"
    assert body["status"] == 422
    assert isinstance(body["errors"], list)
    assert body["errors"], "errors array should not be empty"
    err = body["errors"][0]
    assert {"field", "type", "message"} <= err.keys()
    assert err["field"].endswith("n")


def test_problem_details_exception_passes_through(client: TestClient) -> None:
    r = client.get("/raise/pd/short")
    assert r.status_code == 418
    body = r.json()
    assert body["type"] == f"{PROBLEM_URN_BASE}:test:custom"
    assert body["title"] == "Custom"
    assert body["detail"] == "short"
    assert body["hint"] == "teapot"


def test_problem_response_has_required_keys(client: TestClient) -> None:
    r = client.get("/raise/bru/height_required")
    body = r.json()
    for required in ("type", "title", "status"):
        assert required in body
    # `type` MUST be a URN, not a URL — RFC 7807 allows either but the
    # mobile contract pins URNs.
    assert body["type"].startswith("urn:nova:problem:")


def test_content_type_is_problem_json_even_on_pydantic_error(client: TestClient) -> None:
    r = client.post("/echo", json={})
    assert r.headers["content-type"].startswith("application/problem+json")
