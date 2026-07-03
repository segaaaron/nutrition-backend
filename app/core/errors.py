"""Domain error hierarchy + RFC 7807 (`application/problem+json`) translator.

HTTP status map is the authoritative source — keep it in sync with spec §11.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.core.logging import get_logger

_log = get_logger("errors")

PROBLEM_TYPE_BASE = "https://ms-tech-stack.cloud/errors/"


class DomainError(Exception):
    """Base for every error that is part of the domain contract."""

    http_status: int = 500
    type_slug: str = "internal"
    title: str = "Internal error"

    def __init__(self, detail: str | None = None, **extra: Any) -> None:
        super().__init__(detail or self.title)
        self.detail = detail or self.title
        self.extra = extra


class ValidationError(DomainError):
    http_status = 422
    type_slug = "validation"
    title = "Validation failed"


class NotFoundError(DomainError):
    http_status = 404
    type_slug = "not-found"
    title = "Resource not found"


class ConflictError(DomainError):
    http_status = 409
    type_slug = "conflict"
    title = "Resource conflict"


class GoneError(DomainError):
    http_status = 410
    type_slug = "gone"
    title = "Resource gone"


class LockedError(DomainError):
    http_status = 423
    type_slug = "locked"
    title = "Resource locked"


class BusinessRuleViolation(DomainError):
    http_status = 422
    type_slug = "business-rule"
    title = "Business rule violation"

    def __init__(
        self,
        detail: str | None = None,
        *,
        i18n_key: str | None = None,
        **extra: Any,
    ) -> None:
        """Domain rule violation, raised from application/domain layer.

        Args:
            detail: Canonical EN snake_case rule identifier (e.g.
                ``"onboarding_incomplete"``, ``"segment_unsupported_mvp:..."``).
                Stays as the machine-readable signal for mobile clients.
            i18n_key: Optional explicit translation key. When omitted we
                derive it from ``detail`` by taking the prefix before the
                first ``":"`` (so ``"segment_unsupported_mvp:pediatric"``
                still maps to the ``segment_unsupported_mvp`` translation
                entry). Canonical EN snake_case.
            **extra: Structured context (segment, field, etc.) merged into
                the RFC 7807 body.
        """
        super().__init__(detail, **extra)
        derived = (detail or self.title).split(":", 1)[0] if detail else "business_rule"
        self.i18n_key: str = i18n_key or derived


class IllegalTransition(ConflictError):
    type_slug = "illegal-transition"
    title = "Illegal state transition"


class RateLimited(DomainError):
    http_status = 429
    type_slug = "rate-limited"
    title = "Rate limit exceeded"


class CostCapExceeded(DomainError):
    http_status = 429
    type_slug = "cost-cap-exceeded"
    title = "Cost cap exceeded"


class AuthError(DomainError):
    http_status = 401
    type_slug = "auth"
    title = "Authentication error"


class Unauthenticated(AuthError):
    type_slug = "unauthenticated"
    title = "Authentication required"


class InvalidCredentials(AuthError):
    """Login / OTP-verify: email+password (or OTP code) did not match.

    Distinct from :class:`Unauthenticated` so the iOS client can render a
    contextual message ("Email o contraseña incorrectos") instead of the
    generic "Sesión expirada" copy that suits a missing/expired token.
    """

    type_slug = "invalid-credentials"
    title = "Invalid credentials"


class AuthTicketInvalid(AuthError):
    type_slug = "auth-ticket-invalid"
    title = "Auth ticket invalid"


class Forbidden(AuthError):
    http_status = 403
    type_slug = "forbidden"
    title = "Forbidden"


class UpstreamError(DomainError):
    http_status = 502
    type_slug = "upstream"
    title = "Upstream error"


class EXIFLeakError(DomainError):
    """Fail-closed: any image with surviving GPS EXIF after compression
    aborts the request with 500 rather than silently store a leaking blob.
    """

    http_status = 500
    type_slug = "exif-leak"
    title = "EXIF strip verification failed"


def problem_for(exc: DomainError) -> dict[str, Any]:
    body: dict[str, Any] = {
        "type": f"{PROBLEM_TYPE_BASE}{exc.type_slug}",
        "title": exc.title,
        "status": exc.http_status,
        "detail": exc.detail,
    }
    if exc.extra:
        body.update(exc.extra)
    return body


def register_exception_handlers(app: FastAPI) -> None:
    # Local imports to keep this module framework-light and avoid a
    # cycle with `app.shared.i18n` (which imports nothing from core).
    from app.shared.i18n import TranslatorProtocol, resolve_locale

    async def _maybe_translate(
        request: Request,
        i18n_key: str,
        en_title: str,
        en_detail: str | None,
    ) -> tuple[str, str | None]:
        """Translate ``(title, detail)`` via ``app.state.translator``.

        Header-only locale resolution (no DB profile lookup on error path —
        KISS, matches the contract documented in
        ``app/core/problem_details.py``).
        """
        translator: TranslatorProtocol | None = getattr(
            request.app.state, "translator", None
        )
        if translator is None:
            return en_title, en_detail
        locale = resolve_locale(
            request.headers.get("accept-language"), profile_locale=None
        )
        title_key = f"{i18n_key}.title"
        title = await translator.translate("error", title_key, locale)
        if title == title_key:
            title = en_title
        detail = en_detail
        if en_detail is not None:
            detail_key = f"{i18n_key}.detail"
            translated = await translator.translate("error", detail_key, locale)
            if translated != detail_key:
                detail = translated
        return title, detail

    @app.exception_handler(DomainError)
    async def _domain_handler(request: Request, exc: DomainError) -> JSONResponse:
        # Log every domain error so failures are always traceable server-side.
        # 5xx = ERROR (unexpected); 4xx = WARNING (client mistake).
        log_fn = _log.error if exc.http_status >= 500 else _log.warning
        _RESERVED = frozenset({"type", "status", "detail", "path", "method", "retry_after", "retry_after_s"})
        log_fn(
            "domain_error",
            exc_type=type(exc).__name__,
            status=exc.http_status,
            detail=exc.detail,
            path=request.url.path,
            method=request.method,
            extra={k: v for k, v in exc.extra.items() if k not in _RESERVED},
        )

        headers: dict[str, str] | None = None
        # RFC 6585 §4 / RFC 7231 §7.1.3: Retry-After on 429/503 when
        # the domain layer signalled a bounded retry window.
        if exc.http_status in (429, 503):
            ra = exc.extra.get("retry_after") or exc.extra.get("retry_after_s")
            if ra is not None:
                headers = {"Retry-After": str(int(ra))}
        # Two-tier i18n lookup (option B, 2026-06-07):
        # 1. Detail-specific key (e.g. "password_too_short") — when the
        #    raised exception carries a detail string that the catalogue
        #    knows, use that translation. This keeps the generic
        #    `business_rule`/`conflict`/`not_found` parents while letting
        #    iOS render user-facing copy without a client-side switch.
        # 2. Class-level key (type_slug → underscores) — fallback for any
        #    raise whose detail string is not in the catalogue.
        class_key = exc.type_slug.replace("-", "_")
        detail_key = exc.detail if isinstance(exc.detail, str) else ""
        # Detail-specific lookup only applies when the raw detail is a
        # snake_case slug (the convention the catalogue uses). Anything
        # else (free text, error chains "x:y:z") falls through.
        i18n_key = class_key
        if detail_key and all(c.isalnum() or c == "_" for c in detail_key):
            translator: TranslatorProtocol | None = getattr(
                request.app.state, "translator", None
            )
            if translator is not None:
                locale = resolve_locale(
                    request.headers.get("accept-language"),
                    profile_locale=None,
                )
                title_probe = await translator.translate(
                    "error", f"{detail_key}.title", locale
                )
                if title_probe != f"{detail_key}.title":
                    i18n_key = detail_key
        title, detail = await _maybe_translate(
            request, i18n_key, exc.title, exc.detail
        )
        body = problem_for(exc)
        body["title"] = title
        if detail is not None:
            body["detail"] = detail
        # Always overwrite — i18n translation wins over any exc.extra["message"].
        body["message"] = detail if detail is not None else title
        return JSONResponse(
            status_code=exc.http_status,
            content=body,
            media_type="application/problem+json",
            headers=headers,
        )
