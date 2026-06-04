"""FastAPI dependencies: session, current user, Idempotency-Key resolver,
rate-limit binders.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Annotated
from uuid import UUID

from fastapi import Depends, Header, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_sessionmaker
from app.core.errors import Forbidden, Unauthenticated
from app.core.event_bus import get_event_bus
from app.core.redis import get_redis
from app.identity.application.use_cases import (
    CancelDeletion,
    DeleteAccount,
    ExportData,
    LoginUser,
    Logout,
    OAuthLogin,
    RefreshTokens,
    RegisterUser,
    SendOtp,
    VerifyOtp,
)
from app.identity.infrastructure.jwt_signer import JwtSigner
from app.identity.infrastructure.oauth_verifiers import (
    AppleOAuthVerifier,
    GoogleOAuthVerifier,
)
from app.identity.infrastructure.password_hasher import Argon2PasswordHasher
from app.identity.infrastructure.repositories import (
    SqlOtpRepository,
    SqlRefreshTokenRepository,
    SqlUserRepository,
)

_bearer = HTTPBearer(auto_error=False)
_jwt_singleton: JwtSigner | None = None
_hasher_singleton: Argon2PasswordHasher | None = None


def get_jwt() -> JwtSigner:
    global _jwt_singleton
    if _jwt_singleton is None:
        _jwt_singleton = JwtSigner()
    return _jwt_singleton


def get_hasher() -> Argon2PasswordHasher:
    global _hasher_singleton
    if _hasher_singleton is None:
        _hasher_singleton = Argon2PasswordHasher()
    return _hasher_singleton


async def get_session() -> AsyncIterator[AsyncSession]:
    sm = get_sessionmaker()
    async with sm() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


SessionDep = Annotated[AsyncSession, Depends(get_session)]


async def get_current_user(
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    session: SessionDep,
) -> UUID:
    if creds is None or creds.scheme.lower() != "bearer":
        raise Unauthenticated("missing_bearer")
    claims = await get_jwt().verify_access(creds.credentials)
    sub = claims.get("sub")
    if not sub:
        raise Unauthenticated("missing_sub")
    user_id = UUID(sub)
    # Cheap freshness check — user must exist and not be hard-deleted.
    user = await SqlUserRepository(session).get_by_id(user_id)
    if user is None or user.is_deleted:
        raise Unauthenticated("user_gone")
    return user_id


async def require_admin(
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    session: SessionDep,
) -> UUID:
    if creds is None or creds.scheme.lower() != "bearer":
        raise Unauthenticated("missing_bearer")
    claims = await get_jwt().verify_access(creds.credentials)
    if claims.get("role") != "admin":
        raise Forbidden("admin_required")
    user_id = UUID(claims["sub"])
    user = await SqlUserRepository(session).get_by_id(user_id)
    if user is None or user.is_deleted:
        raise Unauthenticated("user_gone")
    return user_id


def require_role(min_role: Role):  # type: ignore[name-defined]
    """RBAC dependency factory — endpoint authorises iff JWT claim role >= min_role.

    Usage:
        @router.get("/admin/x", dependencies=[Depends(require_role(Role.ADMIN))])

    OWASP API5 (Broken Function Level Authorization), ASVS V4.
    """
    from app.identity.domain.roles import role_at_least

    async def _dep(
        creds: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
        session: SessionDep,
    ) -> UUID:
        if creds is None or creds.scheme.lower() != "bearer":
            raise Unauthenticated("missing_bearer")
        claims = await get_jwt().verify_access(creds.credentials)
        role_claim = str(claims.get("role") or "")
        if not role_at_least(role_claim, min_role):
            raise Forbidden(f"role_required:{min_role.to_str()}")
        sub = claims.get("sub")
        if not sub:
            raise Unauthenticated("missing_sub")
        user_id = UUID(sub)
        user = await SqlUserRepository(session).get_by_id(user_id)
        if user is None or user.is_deleted:
            raise Unauthenticated("user_gone")
        return user_id

    return _dep


CurrentUserDep = Annotated[UUID, Depends(get_current_user)]


async def db_lookup_idempotent(session: AsyncSession, rkey: str) -> dict | None:
    """Check Postgres for a cached idempotency response (Redis fallback)."""
    row = (
        await session.execute(
            text(
                "SELECT response_body FROM idempotency_keys "
                "WHERE key = :k AND expires_at > now()"
            ),
            {"k": rkey},
        )
    ).first()
    if row is None:
        return None
    body = row[0]
    return body if isinstance(body, dict) else json.loads(body)


async def idempotency_key(
    request: Request,
    session: SessionDep,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    user_id: CurrentUserDep | None = None,  # type: ignore[assignment]
) -> tuple[str, str] | None:
    """Returns (redis_key, cached_response_json) if replay; otherwise (key, "").

    `None` means client did not opt into idempotency for this request.
    On Redis miss, falls back to Postgres (survives Redis restart).
    """
    if not idempotency_key:
        return None
    redis = get_redis()
    import hashlib

    composite = f"{user_id}:{request.url.path}:{idempotency_key}"
    rkey = "idem:" + hashlib.sha256(composite.encode()).hexdigest()
    cached = await redis.get(rkey)
    if cached:
        return (rkey, cached)
    body = await db_lookup_idempotent(session, rkey)
    if body is not None:
        await redis.set(rkey, json.dumps(body), ex=24 * 3600)
        return (rkey, json.dumps(body))
    return (rkey, "")


async def remember_idempotent(
    rkey: str,
    body: dict,
    *,
    session: AsyncSession,
    redis=None,
) -> None:
    """Dual-write idempotency response to Redis and Postgres."""
    r = redis or get_redis()
    payload = json.dumps(body)
    expires = datetime.now(UTC) + timedelta(hours=24)
    await r.set(rkey, payload, ex=24 * 3600)
    await session.execute(
        text(
            """
        INSERT INTO idempotency_keys (key, response_body, expires_at)
        VALUES (:k, CAST(:b AS jsonb), :e)
        ON CONFLICT (key) DO NOTHING
    """
        ),
        {"k": rkey, "b": payload, "e": expires},
    )


# --- Use-case factories (DI sugar) ---


def make_register(session: SessionDep) -> RegisterUser:
    return RegisterUser(
        users=SqlUserRepository(session),
        refresh_tokens=SqlRefreshTokenRepository(session),
        hasher=get_hasher(),
        jwt=get_jwt(),
        bus=get_event_bus(),
    )


def make_login(session: SessionDep) -> LoginUser:
    return LoginUser(
        users=SqlUserRepository(session),
        refresh_tokens=SqlRefreshTokenRepository(session),
        hasher=get_hasher(),
        jwt=get_jwt(),
        bus=get_event_bus(),
    )


def make_refresh(session: SessionDep) -> RefreshTokens:
    return RefreshTokens(
        users=SqlUserRepository(session),
        refresh_tokens=SqlRefreshTokenRepository(session),
        jwt=get_jwt(),
        bus=get_event_bus(),
    )


def make_logout(session: SessionDep) -> Logout:
    return Logout(
        refresh_tokens=SqlRefreshTokenRepository(session),
        jwt=get_jwt(),
    )


def make_oauth(session: SessionDep, provider: str) -> OAuthLogin:
    verifier = GoogleOAuthVerifier() if provider == "google" else AppleOAuthVerifier()
    return OAuthLogin(
        users=SqlUserRepository(session),
        refresh_tokens=SqlRefreshTokenRepository(session),
        verifier=verifier,
        jwt=get_jwt(),
        bus=get_event_bus(),
        provider=provider,
    )


def make_send_otp(session: SessionDep) -> SendOtp:
    return SendOtp(
        users=SqlUserRepository(session),
        otps=SqlOtpRepository(session),
        hasher=get_hasher(),
    )


def make_verify_otp(session: SessionDep) -> VerifyOtp:
    return VerifyOtp(
        users=SqlUserRepository(session),
        otps=SqlOtpRepository(session),
        refresh_tokens=SqlRefreshTokenRepository(session),
        hasher=get_hasher(),
        jwt=get_jwt(),
        bus=get_event_bus(),
    )


def make_delete(session: SessionDep) -> DeleteAccount:
    return DeleteAccount(users=SqlUserRepository(session), bus=get_event_bus())


def make_cancel_delete(session: SessionDep) -> CancelDeletion:
    return CancelDeletion(users=SqlUserRepository(session), bus=get_event_bus())


def make_export(session: SessionDep) -> ExportData:
    return ExportData(users=SqlUserRepository(session))


# --- OWASP API1 (BOLA) defence ---

# Allowlist of (table, id_col, user_col) tuples permitted by `assert_owns`.
# SQL identifiers cannot be bound — defence-in-depth requires a closed set so
# that no caller (current or future) can pass attacker-controlled values into
# the identifier slot. Add a row here when introducing a new owned resource.
_ASSERT_OWNS_ALLOWLIST: frozenset[tuple[str, str, str]] = frozenset(
    {
        ("food_logs", "id", "user_id"),
        ("fasting_sessions", "id", "user_id"),
        ("progress_photos", "id", "user_id"),
        ("plans", "id", "user_id"),
        ("grocery_lists", "id", "user_id"),
        ("grocery_items", "id", "user_id"),
        ("vision_jobs", "id", "user_id"),
        ("coach_conversations", "id", "user_id"),
        ("notifications", "id", "user_id"),
        ("invoices", "id", "user_id"),
        ("subscriptions", "id", "user_id"),
        ("user_profiles", "user_id", "user_id"),
    }
)


async def assert_owns(
    session: AsyncSession,
    *,
    table: str,
    resource_id: UUID | str,
    user_id: UUID,
    id_col: str = "id",
    user_col: str = "user_id",
) -> None:
    """Raise NotFoundError / Forbidden if ``resource_id`` does not belong to ``user_id``.

    OWASP API1 (BOLA) defence — call before any read/write on a user-owned
    resource accessed by external ID.

    Args:
        session: Active async DB session.
        table: Table name (e.g. ``"food_logs"``).
        resource_id: UUID of the row being accessed.
        user_id: UUID from the verified JWT (``current_user``).
        id_col: Primary-key column name (default ``"id"``).
        user_col: Ownership column name (default ``"user_id"``).

    Raises:
        ValueError: When ``(table, id_col, user_col)`` is not in the closed
            allowlist. SQL identifiers cannot be parameterised, so this is the
            only safe pattern.
    """
    from app.core.errors import Forbidden, NotFoundError  # local to avoid circular

    triple = (table, id_col, user_col)
    if triple not in _ASSERT_OWNS_ALLOWLIST:
        raise ValueError(
            f"assert_owns_disallowed_identifier: {triple!r} not in allowlist. "
            "Add an explicit row to _ASSERT_OWNS_ALLOWLIST."
        )

    # S608 noqa: identifiers validated against closed allowlist immediately
    # above; resource_id is bound. No injection vector.
    row = (
        await session.execute(
            text(f"SELECT {user_col} FROM {table} WHERE {id_col} = :rid"),  # noqa: S608
            {"rid": str(resource_id)},
        )
    ).first()
    if row is None:
        raise NotFoundError(f"{table}_not_found")
    if str(row[0]) != str(user_id):
        raise Forbidden("not_owner")
