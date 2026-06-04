"""RFC 7807 Problem Details — `urn:nova:problem:*` scheme.

This module layers a stricter, spec-aligned problem mapping on top of the
generic `app/core/errors.py` translator (which uses
`https://ms-tech-stack.cloud/errors/<slug>` URLs).

The mobile contract (docs/mobile/ONBOARDING_API_CONTRACT.md §5, PLAN §3)
mandates URNs of the form ``urn:nova:problem:<context>:<rule>``.

Mapping rules (BusinessRuleViolation.detail string -> URN):
    "segment_unsupported_mvp:..."                  -> plan:segment-unsupported-mvp
    "allergen_unmapped_requires_review"            -> plan:allergen-unmapped-requires-review
    "trimester_required_for_pregnancy"             -> plan:trimester-required-for-pregnancy
    "breastfeeding_status_required_for_lactation"  -> plan:breastfeeding-status-required-for-lactation
    "height_required"                              -> plan:height-required
    "onboarding_incomplete"                        -> plan:onboarding-incomplete
    "pediatric_outside_mvp_scope"                  -> plan:pediatric-outside-mvp-scope
    "geriatric_requires_specialist_review"         -> plan:geriatric-requires-specialist-review
    "profile_missing:<field>"                      -> plan:profile-missing

NotFoundError                                      -> resource:not-found
RequestValidationError                             -> validation:invalid-field

Other DomainError subclasses fall through to the legacy handler in
`app.core.errors.register_exception_handlers`. Callers should register
*both* handler sets; this module's handler runs first because FastAPI
dispatches on the most specific class.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.core.errors import BusinessRuleViolation, NotFoundError

PROBLEM_URN_BASE = "urn:nova:problem"
PROBLEM_CONTENT_TYPE = "application/problem+json"


class ProblemDetails(Exception):
    """RFC 7807 problem details, raisable from any layer.

    `type` MUST be a URN (`urn:nova:problem:<context>:<rule>`), not a URL.
    """

    def __init__(
        self,
        *,
        type: str,
        title: str,
        status: int,
        detail: str | None = None,
        instance: str | None = None,
        extras: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(detail or title)
        self.type = type
        self.title = title
        self.status = status
        self.detail = detail
        self.instance = instance
        self.extras: dict[str, Any] = extras or {}

    def to_body(self) -> dict[str, Any]:
        body: dict[str, Any] = {
            "type": self.type,
            "title": self.title,
            "status": self.status,
        }
        if self.detail is not None:
            body["detail"] = self.detail
        if self.instance is not None:
            body["instance"] = self.instance
        body.update(self.extras)
        return body


# --- BusinessRuleViolation.detail -> (urn-suffix, title) ---
_PLAN_RULE_TITLES: dict[str, tuple[str, str]] = {
    "allergen_unmapped_requires_review": (
        "plan:allergen-unmapped-requires-review",
        "Allergen unmapped — specialist review required",
    ),
    "trimester_required_for_pregnancy": (
        "plan:trimester-required-for-pregnancy",
        "Trimester required for pregnancy",
    ),
    "breastfeeding_status_required_for_lactation": (
        "plan:breastfeeding-status-required-for-lactation",
        "Breastfeeding status required for lactation",
    ),
    "height_required": (
        "plan:height-required",
        "Height required",
    ),
    "onboarding_incomplete": (
        "plan:onboarding-incomplete",
        "Onboarding incomplete",
    ),
    "pediatric_outside_mvp_scope": (
        "plan:pediatric-outside-mvp-scope",
        "Pediatric users outside MVP scope",
    ),
    "geriatric_requires_specialist_review": (
        "plan:geriatric-requires-specialist-review",
        "Geriatric users require specialist review",
    ),
}


def _classify_business_rule(detail: str) -> tuple[str, str, dict[str, Any]]:
    """Return (urn_suffix, title, extras) for a BusinessRuleViolation detail."""
    if detail.startswith("segment_unsupported_mvp:"):
        segment = detail.split(":", 1)[1]
        return (
            "plan:segment-unsupported-mvp",
            "User segment not supported in MVP",
            {"segment": segment},
        )
    if detail.startswith("profile_missing:"):
        field = detail.split(":", 1)[1]
        return (
            "plan:profile-missing",
            "Required profile field missing",
            {"field": field},
        )
    if detail in _PLAN_RULE_TITLES:
        suffix, title = _PLAN_RULE_TITLES[detail]
        return (suffix, title, {})
    return ("business-rule", "Business rule violation", {})


def _problem_response(
    *,
    type_: str,
    title: str,
    status: int,
    detail: str | None,
    instance: str | None,
    extras: dict[str, Any] | None = None,
) -> JSONResponse:
    body: dict[str, Any] = {"type": type_, "title": title, "status": status}
    if detail is not None:
        body["detail"] = detail
    if instance is not None:
        body["instance"] = instance
    if extras:
        body.update(extras)
    return JSONResponse(status_code=status, content=body, media_type=PROBLEM_CONTENT_TYPE)


async def _problem_details_handler(
    request: Request, exc: Exception
) -> JSONResponse:  # noqa: ARG001
    assert isinstance(exc, ProblemDetails)
    return JSONResponse(
        status_code=exc.status,
        content=exc.to_body(),
        media_type=PROBLEM_CONTENT_TYPE,
    )


async def _business_rule_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, BusinessRuleViolation)
    suffix, title, extras = _classify_business_rule(exc.detail)
    return _problem_response(
        type_=f"{PROBLEM_URN_BASE}:{suffix}",
        title=title,
        status=exc.http_status,
        detail=exc.detail,
        instance=str(request.url.path),
        extras={**exc.extra, **extras} if exc.extra else extras,
    )


async def _not_found_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, NotFoundError)
    return _problem_response(
        type_=f"{PROBLEM_URN_BASE}:resource:not-found",
        title="Resource not found",
        status=404,
        detail=exc.detail,
        instance=str(request.url.path),
        extras=exc.extra or None,
    )


async def _validation_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)
    errors: list[dict[str, Any]] = []
    for err in exc.errors():
        loc = err.get("loc", ())
        errors.append(
            {
                "field": ".".join(str(p) for p in loc),
                "type": err.get("type", "invalid"),
                "message": err.get("msg", ""),
            }
        )
    return _problem_response(
        type_=f"{PROBLEM_URN_BASE}:validation:invalid-field",
        title="Request validation failed",
        status=422,
        detail="One or more fields failed validation.",
        instance=str(request.url.path),
        extras={"errors": errors},
    )


def register_problem_handlers(app: FastAPI) -> None:
    """Wire RFC 7807 problem-details handlers into the FastAPI app.

    Idempotent: safe to call multiple times (FastAPI overwrites handlers
    keyed by exception class).
    """
    app.add_exception_handler(ProblemDetails, _problem_details_handler)
    app.add_exception_handler(BusinessRuleViolation, _business_rule_handler)
    app.add_exception_handler(NotFoundError, _not_found_handler)
    app.add_exception_handler(RequestValidationError, _validation_handler)


__all__ = [
    "PROBLEM_CONTENT_TYPE",
    "PROBLEM_URN_BASE",
    "ProblemDetails",
    "register_problem_handlers",
]
