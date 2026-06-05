"""Identity use cases. Pure application logic — no FastAPI / SQL imports.

Concentrated in one module to keep wiring obvious and code review compact.
Each use case is a callable class with `__call__` and explicit dependencies.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from app.core.errors import (
    BusinessRuleViolation,
    ConflictError,
    Forbidden,
    GoneError,
    LockedError,
    NotFoundError,
    Unauthenticated,
)
from app.core.event_bus import EventBus
from app.identity.domain.entities import OtpCode, OtpPurpose, RefreshToken, User
from app.identity.domain.events import (
    OtpLocked,
    RefreshTokenIssued,
    RefreshTokenReused,
    UserDeletionCancelled,
    UserDeletionScheduled,
    UserLoggedIn,
    UserRegistered,
)
from app.identity.domain.ports import (
    JwtSigner,
    OAuthVerifier,
    OtpRepository,
    PasswordHasher,
    RefreshTokenRepository,
    UserRepository,
)
from app.identity.domain.value_objects import Email
from app.shared.domain.email_sender import EmailSender
from app.shared.i18n.locale_resolver import Locale

OTP_TTL = timedelta(minutes=10)
OTP_MAX_ATTEMPTS = 5
OTP_LOCK_DURATION = timedelta(minutes=15)
REFRESH_TTL = timedelta(days=30)
DELETION_GRACE = timedelta(days=30)


def _now() -> datetime:
    return datetime.now(tz=UTC)


@dataclass(slots=True)
class TokenPair:
    access: str
    refresh: str
    user_id: UUID


# ---------------------------------------------------------------------------
# Registration / login
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class RegisterUser:
    users: UserRepository
    refresh_tokens: RefreshTokenRepository
    hasher: PasswordHasher
    jwt: JwtSigner
    bus: EventBus

    async def __call__(self, *, email: str, password: str) -> TokenPair:
        e = Email(email).normalized
        existing = await self.users.get_by_email(e)
        if existing is not None:
            raise ConflictError("email_already_registered")
        if len(password) < 8:
            raise BusinessRuleViolation("password_too_short")

        now = _now()
        user = User(
            id=uuid4(),
            email=e,
            password_hash=self.hasher.hash(password),
            oauth_provider=None,
            oauth_subject=None,
            email_verified=False,
            role="user",
            created_at=now,
        )
        await self.users.add(user)
        await self.bus.publish(UserRegistered(user_id=user.id, email=e, at=now))

        return await _issue_token_pair(
            user,
            self.refresh_tokens,
            self.jwt,
            self.bus,
            method="password",
        )


@dataclass(slots=True)
class LoginUser:
    users: UserRepository
    refresh_tokens: RefreshTokenRepository
    hasher: PasswordHasher
    jwt: JwtSigner
    bus: EventBus

    async def __call__(self, *, email: str, password: str) -> TokenPair:
        e = Email(email).normalized
        user = await self.users.get_by_email(e)
        if user is None or user.password_hash is None or user.is_deleted:
            raise Unauthenticated("invalid_credentials")
        if not self.hasher.verify(password, user.password_hash):
            raise Unauthenticated("invalid_credentials")
        return await _issue_token_pair(
            user,
            self.refresh_tokens,
            self.jwt,
            self.bus,
            method="password",
        )


async def _issue_token_pair(
    user: User,
    refresh_tokens: RefreshTokenRepository,
    jwt: JwtSigner,
    bus: EventBus,
    *,
    method: str,
    family_id: UUID | None = None,
    parent_id: UUID | None = None,
) -> TokenPair:
    now = _now()
    access = jwt.sign_access(user_id=user.id, role=user.role)
    refresh_plain = jwt.sign_refresh_value()
    refresh_hash = jwt.hash_refresh(refresh_plain)
    family = family_id or uuid4()
    token = RefreshToken(
        id=uuid4(),
        user_id=user.id,
        token_hash=refresh_hash,
        family_id=family,
        parent_id=parent_id,
        expires_at=now + REFRESH_TTL,
        created_at=now,
    )
    await refresh_tokens.add(token)
    await bus.publish_many(
        [
            UserLoggedIn(user_id=user.id, at=now, method=method),
            RefreshTokenIssued(user_id=user.id, token_id=token.id, family_id=family, at=now),
        ]
    )
    return TokenPair(access=access, refresh=refresh_plain, user_id=user.id)


# ---------------------------------------------------------------------------
# Refresh — family reuse detection (RFC 6819 §5.2.2.3)
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class RefreshTokens:
    users: UserRepository
    refresh_tokens: RefreshTokenRepository
    jwt: JwtSigner
    bus: EventBus

    async def __call__(self, *, refresh_plain: str) -> TokenPair:
        now = _now()
        token_hash = self.jwt.hash_refresh(refresh_plain)
        rec = await self.refresh_tokens.get_by_hash(token_hash)
        if rec is None:
            raise Unauthenticated("refresh_invalid")
        if rec.expires_at <= now:
            raise Unauthenticated("refresh_expired")
        if rec.revoked_at is not None:
            # Reuse detected — revoke entire family.
            await self.refresh_tokens.mark_reused(rec.id, now)
            n = await self.refresh_tokens.revoke_family(rec.family_id, now)
            await self.bus.publish(
                RefreshTokenReused(
                    user_id=rec.user_id,
                    token_id=rec.id,
                    family_id=rec.family_id,
                    at=now,
                )
            )
            raise Unauthenticated(f"refresh_reused_family_revoked:{n}")

        # Valid: rotate. Mark current revoked, issue new in same family.
        await self.refresh_tokens.revoke(rec.id, now)
        user = await self.users.get_by_id(rec.user_id)
        if user is None or user.is_deleted:
            raise Unauthenticated("user_gone")
        return await _issue_token_pair(
            user,
            self.refresh_tokens,
            self.jwt,
            self.bus,
            method="refresh",
            family_id=rec.family_id,
            parent_id=rec.id,
        )


@dataclass(slots=True)
class Logout:
    refresh_tokens: RefreshTokenRepository
    jwt: JwtSigner

    async def __call__(self, *, refresh_plain: str, access_token: str | None = None) -> None:
        rec = await self.refresh_tokens.get_by_hash(self.jwt.hash_refresh(refresh_plain))
        if rec is None or rec.revoked_at is not None:
            return  # idempotent
        await self.refresh_tokens.revoke(rec.id, _now())
        # OWASP API2: revoke access token jti so it cannot be reused until expiry.
        if access_token:
            from app.core.config import get_settings
            from app.identity.infrastructure.jwt_signer import revoke_jti

            try:
                claims = await self.jwt.verify_access(access_token)
                jti = claims.get("jti")
                if jti:
                    await revoke_jti(jti, ttl_seconds=get_settings().jwt_access_ttl_seconds)
            except Exception:  # noqa: BLE001,S110 — invalid/expired token must not block logout
                pass


# ---------------------------------------------------------------------------
# OAuth (Google / Apple)
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class OAuthLogin:
    users: UserRepository
    refresh_tokens: RefreshTokenRepository
    verifier: OAuthVerifier
    jwt: JwtSigner
    bus: EventBus
    provider: str  # 'google' | 'apple'

    async def __call__(self, *, id_token: str) -> TokenPair:
        claims = await self.verifier.verify_id_token(id_token)
        subject = claims["sub"]
        email = claims.get("email", "").strip().lower()
        email_verified = bool(claims.get("email_verified", False))
        if not subject:
            raise Unauthenticated("oauth_no_subject")

        user = await self.users.get_by_oauth(self.provider, subject)
        if user is None and email:
            user = await self.users.get_by_email(email)
        if user is None:
            user = User(
                id=uuid4(),
                email=email or f"{subject}@{self.provider}.oauth",
                password_hash=None,
                oauth_provider=self.provider,
                oauth_subject=subject,
                email_verified=email_verified,
                role="user",
                created_at=_now(),
            )
            await self.users.add(user)
            await self.bus.publish(UserRegistered(user_id=user.id, email=user.email, at=_now()))
        elif user.oauth_provider is None:
            # Link OAuth to existing email-only account
            user.oauth_provider = self.provider
            user.oauth_subject = subject
            user.email_verified = user.email_verified or email_verified
            await self.users.update(user)

        return await _issue_token_pair(
            user,
            self.refresh_tokens,
            self.jwt,
            self.bus,
            method=f"oauth_{self.provider}",
        )


# ---------------------------------------------------------------------------
# OTP
# ---------------------------------------------------------------------------


def _new_code() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


@dataclass(slots=True)
class SendOtp:
    users: UserRepository
    otps: OtpRepository
    hasher: PasswordHasher
    # Optional — when provided, the use-case renders the OTP email template
    # and dispatches via the sender. When None (default), the plaintext code
    # is returned to the caller and the presentation layer decides what to
    # do with it (dev echo, queue an Arq job, etc.). Keeps backward compat
    # with existing tests and routers.
    email_sender: EmailSender | None = None
    # Locale for outbound email. Resolved by the presentation layer via
    # ``resolve_email_locale(profile_locale, accept_language)`` (D5) and
    # injected by ``make_send_otp``. ``None`` → renderer falls back to ``es``
    # (D4). The use case stays framework-agnostic: no Accept-Language
    # parsing here, no profile-context coupling.
    locale: Locale | None = None

    async def __call__(self, *, email: str, purpose: OtpPurpose) -> str:
        """Generate + persist an OTP, optionally dispatch via email.

        Always returns the plaintext code. When ``email_sender`` is wired,
        the code is also sent via email. Email delivery failure does NOT
        roll back OTP persistence — the user can retry. Errors are logged
        and re-raised as :class:`EmailDeliveryError` so the router can map
        to 502.

        Dispatch model decision (2026-06-04): INLINE — caller awaits the
        Resend roundtrip during the request. Closed-beta scope (<=100
        users), Resend p95 ~200ms, overhead acceptable.

        Migration trigger to Arq enqueue:
        - p95 ``/v1/identity/otp/send`` > 300ms in production
        - User-reported delivery delay
        - Resend rate-limit hit (>100 emails/min sustained)

        Worker task ``worker.email_tasks.send_email_task`` is registered
        but currently unused from this path. Switch via the
        ``make_send_otp`` dependency factory when a trigger fires.
        """
        user = await self.users.get_by_email(Email(email).normalized)
        if user is None:
            raise NotFoundError("user_not_found")
        existing = await self.otps.get_active(user.id, purpose)
        if existing is not None and existing.is_locked(_now()):
            raise LockedError("otp_locked")
        code = _new_code()
        otp = OtpCode(
            id=uuid4(),
            user_id=user.id,
            code_hash=self.hasher.hash(code),
            purpose=purpose,
            expires_at=_now() + OTP_TTL,
        )
        await self.otps.add(otp)

        if self.email_sender is not None:
            # Late import keeps the application layer free of infrastructure
            # template strings at module-load time (and avoids cycles).
            from app.identity.infrastructure.email_templates import render_otp_email

            ttl_minutes = max(1, int(OTP_TTL.total_seconds() // 60))
            rendered = render_otp_email(
                code=code,
                ttl_minutes=ttl_minutes,
                purpose=purpose,
                locale=self.locale,
            )
            await self.email_sender.send(
                to=Email(email).normalized,
                subject=rendered.subject,
                html=rendered.html,
                text=rendered.text,
                idempotency_key=str(otp.id),
            )
        return code


@dataclass(slots=True)
class VerifyOtp:
    users: UserRepository
    otps: OtpRepository
    refresh_tokens: RefreshTokenRepository
    hasher: PasswordHasher
    jwt: JwtSigner
    bus: EventBus

    async def __call__(self, *, email: str, purpose: OtpPurpose, code: str) -> TokenPair:
        user = await self.users.get_by_email(Email(email).normalized)
        if user is None:
            raise NotFoundError("user_not_found")
        otp = await self.otps.get_active(user.id, purpose)
        if otp is None:
            raise NotFoundError("otp_not_found")
        now = _now()
        if otp.is_locked(now):
            raise LockedError("otp_locked")
        if otp.expires_at <= now:
            raise BusinessRuleViolation("otp_expired")
        if not self.hasher.verify(code, otp.code_hash):
            attempts = await self.otps.increment_attempts(otp.id)
            if attempts >= OTP_MAX_ATTEMPTS:
                lock_until = now + OTP_LOCK_DURATION
                await self.otps.lock(otp.id, lock_until)
                await self.bus.publish(
                    OtpLocked(
                        user_id=user.id,
                        purpose=purpose,
                        locked_until=lock_until,
                    )
                )
                raise LockedError("otp_locked")
            raise Unauthenticated("otp_invalid")
        await self.otps.consume(otp.id)
        if purpose == "register":
            user.email_verified = True
            await self.users.update(user)
        return await _issue_token_pair(
            user,
            self.refresh_tokens,
            self.jwt,
            self.bus,
            method="otp",
        )


# ---------------------------------------------------------------------------
# GDPR (ADR-0005)
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class DeleteAccount:
    users: UserRepository
    bus: EventBus

    async def __call__(self, *, user_id: UUID) -> datetime:
        user = await self.users.get_by_id(user_id)
        if user is None:
            raise NotFoundError("user_not_found")
        if user.is_deleted:
            raise GoneError("already_deleted")
        if user.deletion_requested_at is not None:
            # idempotent: return existing scheduled_for
            return user.deletion_requested_at + DELETION_GRACE
        scheduled_for = _now() + DELETION_GRACE
        await self.users.schedule_deletion(user_id, _now())
        await self.bus.publish(UserDeletionScheduled(user_id=user_id, scheduled_for=scheduled_for))
        return scheduled_for


@dataclass(slots=True)
class CancelDeletion:
    users: UserRepository
    bus: EventBus

    async def __call__(self, *, user_id: UUID) -> None:
        user = await self.users.get_by_id(user_id)
        if user is None:
            raise NotFoundError("user_not_found")
        if user.is_deleted:
            raise GoneError("already_deleted")
        if user.deletion_requested_at is None:
            raise ConflictError("no_deletion_pending")
        elapsed = _now() - user.deletion_requested_at
        if elapsed > DELETION_GRACE:
            raise GoneError("grace_elapsed")
        await self.users.cancel_deletion(user_id)
        await self.bus.publish(UserDeletionCancelled(user_id=user_id, at=_now()))


@dataclass(slots=True)
class ExportData:
    users: UserRepository

    async def __call__(self, *, user_id: UUID) -> dict[str, Any]:
        """For MVP returns an inline JSON blob; production hands off to worker."""
        user = await self.users.get_by_id(user_id)
        if user is None:
            raise NotFoundError("user_not_found")
        if user.is_deleted:
            raise Forbidden("account_deleted")
        # The full export is built by worker.export_user_data_task; here we return
        # a minimal acknowledgement payload with the user identity row.
        return {
            "user": {
                "id": str(user.id),
                "email": user.email,
                "email_verified": user.email_verified,
                "created_at": user.created_at.isoformat(),
                "role": user.role,
            },
            "note": "Full export is generated asynchronously; downloadable URL TBD.",
        }
