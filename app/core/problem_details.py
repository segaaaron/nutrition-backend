"""RFC 7807 Problem Details — ``urn:nova:problem:*`` scheme + i18n.

This module layers a stricter, spec-aligned problem mapping on top of the
generic ``app/core/errors.py`` translator (which uses
``https://ms-tech-stack.cloud/errors/<slug>`` URLs).

The mobile contract (docs/mobile/ONBOARDING_API_CONTRACT.md §5, PLAN §3)
mandates URNs of the form ``urn:nova:problem:<context>:<rule>``.

i18n contract (Phase 4 — runtime locale propagation plan §4):

* ``type`` URI **stays EN always** — RFC 7807 spec §3.1: ``type`` is a URI
  reference acting as a stable machine identifier. Translating it would
  break client switches on URN.
* ``title`` and ``detail`` are translated via :class:`TranslatorProtocol`
  using scope ``"error"`` (handler errors) or ``"validation"`` (pydantic
  ``RequestValidationError`` field messages).
* Locale resolution in exception handlers: **header-only**
  (``Accept-Language``). FastAPI exception handlers cannot use ``Depends``
  and we deliberately skip the profile-locale DB lookup on the error path
  (KISS — error rendering must never trigger a DB read or fail).
* Translator lives on ``app.state.translator`` (lifespan-bound singleton).
  When unset (e.g. unit tests building a bare FastAPI app) we fall back
  to the canonical EN ``title`` / ``detail`` — the existing pre-i18n
  behaviour, so legacy tests keep passing.

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
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.core.errors import BusinessRuleViolation, NotFoundError
from app.shared.i18n import Locale, TranslatorProtocol, resolve_locale

PROBLEM_URN_BASE = "urn:nova:problem"
PROBLEM_CONTENT_TYPE = "application/problem+json"

# Translation scopes (must match seed_i18n_errors.py).
_SCOPE_ERROR = "error"
_SCOPE_VALIDATION = "validation"

_TITLE_SUFFIX = ".title"
_DETAIL_SUFFIX = ".detail"


class ProblemDetails(Exception):
    """RFC 7807 problem details, raisable from any layer.

    ``type`` MUST be a URN (``urn:nova:problem:<context>:<rule>``), not a URL.

    ``i18n_key`` is optional — when set, the handler looks up
    ``error.{i18n_key}.title`` / ``error.{i18n_key}.detail`` via Translator
    and replaces ``title`` / ``detail`` with the localised strings. When
    omitted (or translator unavailable) the raw EN strings ship through.
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
        i18n_key: str | None = None,
    ) -> None:
        super().__init__(detail or title)
        self.type = type
        self.title = title
        self.status = status
        self.detail = detail
        self.instance = instance
        self.extras: dict[str, Any] = extras or {}
        self.i18n_key: str | None = i18n_key

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


# --- BusinessRuleViolation.detail -> (urn-suffix, EN title, i18n_key) ---
_PLAN_RULE_TITLES: dict[str, tuple[str, str, str]] = {
    "allergen_unmapped_requires_review": (
        "plan:allergen-unmapped-requires-review",
        "Allergen unmapped — specialist review required",
        "allergen_unmapped_requires_review",
    ),
    "trimester_required_for_pregnancy": (
        "plan:trimester-required-for-pregnancy",
        "Trimester required for pregnancy",
        "trimester_required_for_pregnancy",
    ),
    "breastfeeding_status_required_for_lactation": (
        "plan:breastfeeding-status-required-for-lactation",
        "Breastfeeding status required for lactation",
        "breastfeeding_status_required_for_lactation",
    ),
    "height_required": (
        "plan:height-required",
        "Height required",
        "height_required",
    ),
    "onboarding_incomplete": (
        "plan:onboarding-incomplete",
        "Onboarding incomplete",
        "onboarding_incomplete",
    ),
    "pediatric_outside_mvp_scope": (
        "plan:pediatric-outside-mvp-scope",
        "Pediatric users outside MVP scope",
        "pediatric_outside_mvp_scope",
    ),
    "geriatric_requires_specialist_review": (
        "plan:geriatric-requires-specialist-review",
        "Geriatric users require specialist review",
        "geriatric_requires_specialist_review",
    ),
    "plan_generation_yielded_no_meals": (
        "plan:generation-yielded-no-meals",
        "Plan generation produced no meals for your restrictions",
        "plan_generation_yielded_no_meals",
    ),
    "nutritional_goals_missing": (
        "plan:nutritional-goals-missing",
        "Nutritional goals missing — complete onboarding first",
        "nutritional_goals_missing",
    ),
    "no_candidates_for_meal": (
        "plan:no-candidates-for-meal",
        "No recipes match your restrictions for this meal",
        "no_candidates_for_meal",
    ),
    "region_audit_unavailable": (
        "profile:region-audit-unavailable",
        "Region change audit unavailable — try again",
        "region_audit_unavailable",
    ),
    "duplicate_live_subscription": (
        "billing:duplicate-live-subscription",
        "Active subscription already exists",
        "duplicate_live_subscription",
    ),
    "grocery_generation_yielded_no_items": (
        "grocery:generation-yielded-no-items",
        "Grocery list generation produced no items",
        "grocery_generation_yielded_no_items",
    ),
}


def _classify_business_rule(detail: str) -> tuple[str, str, str, dict[str, Any]]:
    """Return ``(urn_suffix, EN title, i18n_key, extras)`` for a rule detail."""
    if detail.startswith("segment_unsupported_mvp:"):
        segment = detail.split(":", 1)[1]
        return (
            "plan:segment-unsupported-mvp",
            "User segment not supported in MVP",
            "segment_unsupported_mvp",
            {"segment": segment},
        )
    if detail.startswith("profile_missing:"):
        field = detail.split(":", 1)[1]
        return (
            "plan:profile-missing",
            "Required profile field missing",
            "profile_missing",
            {"field": field},
        )
    if detail in _PLAN_RULE_TITLES:
        suffix, title, i18n_key = _PLAN_RULE_TITLES[detail]
        return (suffix, title, i18n_key, {})
    return ("business-rule", "Business rule violation", "business_rule", {})


def _request_locale(request: Request) -> Locale:
    """Header-only locale resolution for the error path (no DB lookup)."""
    header = request.headers.get("accept-language")
    return resolve_locale(header, profile_locale=None)


def _translator(request: Request) -> TranslatorProtocol | None:
    """Return the lifespan-bound translator, or ``None`` if not wired.

    Bare FastAPI apps in unit tests (which don't run the production
    ``create_app`` lifespan) get ``None`` here and fall back to EN.
    """
    return getattr(request.app.state, "translator", None)


async def _translate_pair(
    translator: TranslatorProtocol | None,
    scope: str,
    i18n_key: str,
    locale: Locale,
    fallback_title: str,
    fallback_detail: str | None,
) -> tuple[str, str | None]:
    """Translate (title, detail) with EN fallback on miss / no translator."""
    if translator is None:
        return fallback_title, fallback_detail
    title_key = f"{i18n_key}{_TITLE_SUFFIX}"
    title = await translator.translate(scope, title_key, locale)
    # Echo-on-miss contract: Translator returns the key as-is when the row
    # is absent. Treat that as "fall back to canonical EN" rather than
    # leaking the key to the client.
    if title == title_key:
        title = fallback_title
    detail: str | None = fallback_detail
    if fallback_detail is not None:
        detail_key = f"{i18n_key}{_DETAIL_SUFFIX}"
        translated_detail = await translator.translate(scope, detail_key, locale)
        if translated_detail != detail_key:
            detail = translated_detail
    return title, detail


def _problem_response(
    *,
    type_: str,
    title: str,
    status: int,
    detail: str | None,
    instance: str | None,
    extras: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    body: dict[str, Any] = {"type": type_, "title": title, "status": status}
    if detail is not None:
        body["detail"] = detail
    if instance is not None:
        body["instance"] = instance
    if extras:
        body.update(extras)
    return JSONResponse(
        status_code=status,
        content=body,
        media_type=PROBLEM_CONTENT_TYPE,
        headers=headers,
    )


async def _problem_details_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, ProblemDetails)
    locale = _request_locale(request)
    translator = _translator(request)
    title = exc.title
    detail = exc.detail
    if exc.i18n_key is not None:
        title, detail = await _translate_pair(
            translator,
            _SCOPE_ERROR,
            exc.i18n_key,
            locale,
            exc.title,
            exc.detail,
        )
    body = exc.to_body()
    body["title"] = title
    if detail is not None:
        body["detail"] = detail
    return JSONResponse(
        status_code=exc.status,
        content=body,
        media_type=PROBLEM_CONTENT_TYPE,
    )


async def _business_rule_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, BusinessRuleViolation)
    suffix, en_title, classified_key, classified_extras = _classify_business_rule(
        exc.detail
    )
    # Honor an explicit i18n_key on the exception; fall back to classifier.
    # `BusinessRuleViolation.__init__` derives i18n_key from detail prefix
    # already, so the two normally match — but a caller MAY override.
    chosen_key = (
        exc.i18n_key
        if exc.i18n_key not in ("business_rule", "")
        else classified_key
    )
    locale = _request_locale(request)
    translator = _translator(request)
    title, detail = await _translate_pair(
        translator,
        _SCOPE_ERROR,
        chosen_key,
        locale,
        en_title,
        exc.detail,
    )
    extras = {**exc.extra, **classified_extras} if exc.extra else classified_extras
    return _problem_response(
        type_=f"{PROBLEM_URN_BASE}:{suffix}",
        title=title,
        status=exc.http_status,
        detail=detail,
        instance=str(request.url.path),
        extras=extras,
    )


async def _not_found_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, NotFoundError)
    locale = _request_locale(request)
    translator = _translator(request)
    title, detail = await _translate_pair(
        translator,
        _SCOPE_ERROR,
        "not_found",
        locale,
        "Resource not found",
        exc.detail,
    )
    return _problem_response(
        type_=f"{PROBLEM_URN_BASE}:resource:not-found",
        title=title,
        status=404,
        detail=detail,
        instance=str(request.url.path),
        extras=exc.extra or None,
    )


async def _validation_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)
    locale = _request_locale(request)
    translator = _translator(request)
    env_title, env_detail = await _translate_pair(
        translator,
        _SCOPE_ERROR,
        "validation",
        locale,
        "Request validation failed",
        "One or more fields failed validation.",
    )
    errors: list[dict[str, Any]] = []
    for err in exc.errors():
        loc = err.get("loc", ())
        raw_type = err.get("type", "invalid")
        raw_msg = err.get("msg", "")
        translated_msg = raw_msg
        if translator is not None and raw_type:
            candidate = await translator.translate(
                _SCOPE_VALIDATION, raw_type, locale
            )
            if candidate != raw_type:
                translated_msg = candidate
        errors.append(
            {
                "field": ".".join(str(p) for p in loc),
                "type": raw_type,
                "message": translated_msg,
            }
        )
    return _problem_response(
        type_=f"{PROBLEM_URN_BASE}:validation:invalid-field",
        title=env_title,
        status=422,
        detail=env_detail,
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
