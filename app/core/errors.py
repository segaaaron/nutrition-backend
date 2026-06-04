"""Domain error hierarchy + RFC 7807 (`application/problem+json`) translator.

HTTP status map is the authoritative source — keep it in sync with spec §11.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

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
    @app.exception_handler(DomainError)
    async def _domain_handler(request: Request, exc: DomainError) -> JSONResponse:  # noqa: ARG001
        headers: dict[str, str] | None = None
        # RFC 6585 §4 / RFC 7231 §7.1.3: Retry-After on 429/503 when
        # the domain layer signalled a bounded retry window.
        if exc.http_status in (429, 503):
            ra = exc.extra.get("retry_after") or exc.extra.get("retry_after_s")
            if ra is not None:
                headers = {"Retry-After": str(int(ra))}
        return JSONResponse(
            status_code=exc.http_status,
            content=problem_for(exc),
            media_type="application/problem+json",
            headers=headers,
        )
