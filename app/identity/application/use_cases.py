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
    InvalidCredentials,
    LockedError,
    NotFoundError,
    Unauthenticated,
)
from app.core.event_bus import EventBus
from app.core.logging import get_logger
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
from app.shared.domain.email_sender import EmailDeliveryError, EmailSender
from app.shared.i18n.locale_resolver import Locale

_log = get_logger(__name__)

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
    onboarding_completed: bool = False


# ---------------------------------------------------------------------------
# Registration / login
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class RegisterUser:
    """Pending-registration use case (no ``users`` row created here).

    Contract (2026-06-09 refactor):

    - We DO NOT create a ``users`` row. The user becomes real only after
      ``VerifyOtp`` consumes a valid ``purpose='register'`` OTP that carries
      the pending ``email`` + ``password_hash``.
    - The ``users.get_by_email`` lookup is kept ONLY to short-circuit
      registration attempts for already-verified emails (clearer UX +
      avoids duplicate-email enumeration through the OTP queue).
    - Email-delivery failures from Resend are swallowed (the OTP row was
      already persisted; the client may retry via ``POST /auth/otp/send``).
    - Persistence / unexpected errors propagate so the FastAPI
      ``get_session`` dependency rolls back the transaction cleanly.
      Previously a bare ``except Exception`` swallowed DB errors and left
      the SQLAlchemy session in ``InFailedSqlTransaction``, which then
      crashed at commit-time with a generic HTTP 500. Diagnostic root-cause
      of the reported 500 on ``/auth/register`` (2026-06-09).

    Legacy fields (``refresh_tokens``, ``jwt``, ``bus``) are retained as
    ``None``-defaulted slots so existing test constructors keep compiling.
    They are no longer read — token issuance moved to ``VerifyOtp`` once
    the OTP is consumed.
    """

    users: UserRepository
    hasher: PasswordHasher
    # Optional ``SendOtp`` use case wired by ``make_register``. When set, the
    # register flow auto-dispatches a ``purpose='register'`` OTP to the user
    # email so the client can verify ownership without needing a separate
    # ``POST /auth/otp/send`` call. Email failure does NOT roll back user
    # creation — the user can request a resend via ``/auth/otp/send``.
    send_otp: SendOtp | None = None
    # Legacy / unused — kept for backward-compatible construction (tests).
    refresh_tokens: RefreshTokenRepository | None = None
    jwt: JwtSigner | None = None
    bus: EventBus | None = None

    async def __call__(self, *, email: str, password: str) -> None:
        e = Email(email).normalized
        if len(password) < 8:
            raise BusinessRuleViolation("password_too_short")
        existing = await self.users.get_by_email(e)
        if existing is not None:
            # Email already belongs to a real (verified or unverified) user.
            # We do NOT leak whether the account is verified — same code.
            raise ConflictError("email_already_registered")

        # Auto-send verification OTP for the pending registration. The user
        # row is created only after the OTP is verified.
        if self.send_otp is not None:
            try:
                await self.send_otp(
                    email=e,
                    purpose="register",
                    password_hash=self.hasher.hash(password),
                )
            except EmailDeliveryError:
                # Resend down / 4xx-5xx from provider. The OTP row was
                # already persisted by ``SendOtp`` BEFORE the email leg, so
                # the client can retry delivery via ``POST /auth/otp/send``
                # without losing the pending registration. QA F3: full
                # stacktrace for ops; PII-safe (email logged hashed by the
                # Resend adapter, not here).
                # PII-safe: hash recipient instead of logging the address.
                import hashlib as _hashlib

                _log.exception(
                    "register.otp_dispatch_failed",
                    recipient_hash=_hashlib.sha256(e.encode()).hexdigest()[:16],
                )
            # Any other exception (SQL error, type bug, etc.) MUST propagate
            # so the session rollback in ``get_session`` runs and the client
            # receives a proper 4xx/5xx — NOT a misleading 202 with a
            # poisoned transaction that then 500s at commit time.


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
            raise InvalidCredentials("invalid_credentials")
        if not self.hasher.verify(password, user.password_hash):
            raise InvalidCredentials("invalid_credentials")
        if not user.email_verified:
            # QA F2: do NOT distinguish "wrong password" from "unverified" at
            # the login surface — that combo confirms BOTH "email exists" AND
            # "password correct" which is a credential-stuffing oracle. Same
            # error code; observability via structured log only. iOS surfaces
            # a "Resend code" CTA on every invalid_credentials.
            _log.info("login.blocked_unverified", user_id=str(user.id))
            raise InvalidCredentials("invalid_credentials")
        onboarding_completed = await self.users.get_onboarding_completed(user.id)
        return await _issue_token_pair(
            user,
            self.refresh_tokens,
            self.jwt,
            self.bus,
            method="password",
            onboarding_completed=onboarding_completed,
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
    onboarding_completed: bool = False,
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
    # Observability (QA finding F-O1 / R1): enables ops to debug iOS reports
    # of "wrong onboarding flag" by correlating with the user_profiles
    # transition timestamp. PII-safe — only the user_id + method + flag.
    _log.info(
        "identity.token_issued",
        user_id=str(user.id),
        method=method,
        onboarding_completed=onboarding_completed,
    )
    return TokenPair(
        access=access,
        refresh=refresh_plain,
        user_id=user.id,
        onboarding_completed=onboarding_completed,
    )


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
        # Serialize concurrent refresh requests for the same token.
        # Without this lock two in-flight requests both read revoked_at=None,
        # both pass the check, and both issue new tokens — breaking RFC 6819
        # §5.2.2.3 family-reuse protection. The advisory lock is held until
        # the transaction commits so the second caller re-reads the now-revoked
        # row and hits the reuse-detection branch below.
        await self.refresh_tokens.lock_for_rotation(token_hash)
        # Re-read inside the lock so we see the committed state.
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
        # QA F7: uniform email-verification gate. Refresh tokens issued
        # at register before OTP verify must NOT extend a session for an
        # unverified user — otherwise the bearer can rotate indefinitely
        # despite get_current_user blocking the access path.
        if not user.email_verified:
            raise Unauthenticated("email_not_verified")
        # Cross-table read (QA R3): adds `user_profiles` to the session's
        # working set alongside the pre-existing `users` lookup above. No
        # NEW lock surface — `users` was already in the session and the
        # NOVA migration policy (CLAUDE.md "reversible + zero-downtime")
        # forbids ACCESS EXCLUSIVE locks on either table.
        onboarding_completed = await self.users.get_onboarding_completed(user.id)
        return await _issue_token_pair(
            user,
            self.refresh_tokens,
            self.jwt,
            self.bus,
            method="refresh",
            family_id=rec.family_id,
            parent_id=rec.id,
            onboarding_completed=onboarding_completed,
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
            from redis.exceptions import RedisError

            from app.core.config import get_settings
            from app.core.errors import Unauthenticated
            from app.identity.infrastructure.jwt_signer import revoke_jti

            try:
                claims = await self.jwt.verify_access(access_token)
                jti = claims.get("jti")
                if jti:
                    await revoke_jti(jti, ttl_seconds=get_settings().jwt_access_ttl_seconds)
            except (Unauthenticated, RedisError):
                # Invalid/expired token or Redis hiccup must not block logout
                # — the refresh token is already revoked above. We don't log
                # at exception level because expired-access during logout is
                # the common happy-path; a stack trace would be noisy.
                _log.debug("logout.access_revoke_skipped")


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
            from sqlalchemy.exc import IntegrityError as _IntegrityError

            try:
                await self.users.add(user)
            except _IntegrityError as exc:
                # Race condition: another OAuth callback for the same email
                # raced us to ``INSERT users``. Re-fetch the now-existing
                # row and continue the login flow instead of returning 500.
                # Important since iOS Sign-in-with-Apple may fire twice on
                # fast taps.
                raise ConflictError("user_creation_race") from exc
            await self.bus.publish(UserRegistered(user_id=user.id, email=user.email, at=_now()))
        elif user.oauth_provider is None:
            # Link OAuth to existing email-only account
            user.oauth_provider = self.provider
            user.oauth_subject = subject
            user.email_verified = user.email_verified or email_verified
            await self.users.update(user)

        onboarding_completed = await self.users.get_onboarding_completed(user.id)
        return await _issue_token_pair(
            user,
            self.refresh_tokens,
            self.jwt,
            self.bus,
            method=f"oauth_{self.provider}",
            onboarding_completed=onboarding_completed,
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

    async def __call__(
        self,
        *,
        email: str,
        purpose: OtpPurpose,
        password_hash: str | None = None,
    ) -> str | None:
        """Generate + persist an OTP, optionally dispatch via email.

        Returns the plaintext code on success. Returns ``None`` silently when
        ``purpose != "register"`` and the email has no corresponding user —
        anti-enumeration defence (caller still returns 202 to the client so
        an attacker cannot probe email existence). When ``email_sender`` is
        wired, the code is also sent via email. Email delivery failure does
        NOT roll back OTP persistence — the user can retry. Errors are logged
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
        normalized = Email(email).normalized
        user = await self.users.get_by_email(normalized)
        if user is None and purpose != "register":
            # Anti-enumeration: silently no-op for reset/login when user does
            # not exist. Caller (router) still returns 202 to the client so an
            # attacker cannot probe email existence via this endpoint.
            return None
        if user is not None:
            existing = await self.otps.get_active(user.id, purpose)
        else:
            existing = await self.otps.get_active_by_email(normalized, purpose)
        if existing is not None and existing.is_locked(_now()):
            raise LockedError("otp_locked")
        code = _new_code()
        otp = OtpCode(
            id=uuid4(),
            user_id=user.id if user is not None else None,
            email=normalized,
            password_hash=password_hash,
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
        normalized = Email(email).normalized
        user = await self.users.get_by_email(normalized)
        otp = None
        if user is not None:
            otp = await self.otps.get_active(user.id, purpose)
        if otp is None and purpose == "register":
            otp = await self.otps.get_active_by_email(normalized, purpose)
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
                if user is not None:
                    await self.bus.publish(
                        OtpLocked(
                            user_id=user.id,
                            purpose=purpose,
                            locked_until=lock_until,
                        )
                    )
                raise LockedError("otp_locked")
            raise InvalidCredentials("otp_invalid")
        await self.otps.consume(otp.id)
        if purpose == "register":
            if user is None:
                if otp.password_hash is None:
                    raise BusinessRuleViolation("otp_missing_password")
                user = User(
                    id=uuid4(),
                    email=normalized,
                    password_hash=otp.password_hash,
                    oauth_provider=None,
                    oauth_subject=None,
                    email_verified=True,
                    role="user",
                    created_at=_now(),
                )
                # QA: race condition guard — two concurrent ``VerifyOtp``
                # calls for the same email (e.g. user double-taps) would
                # both find ``user is None`` and race to ``INSERT users``.
                # The UNIQUE constraint on ``users.email`` makes the second
                # insert raise ``IntegrityError`` which bubbles as HTTP 500.
                # Map to a stable 409 so the client can retry login instead.
                from sqlalchemy.exc import IntegrityError as _IntegrityError

                try:
                    await self.users.add(user)
                except _IntegrityError as exc:
                    raise ConflictError("email_already_registered") from exc
                await self.bus.publish(
                    UserRegistered(user_id=user.id, email=user.email, at=_now())
                )
            else:
                user.email_verified = True
                await self.users.update(user)
        onboarding_completed = await self.users.get_onboarding_completed(user.id)
        return await _issue_token_pair(
            user,
            self.refresh_tokens,
            self.jwt,
            self.bus,
            method="otp",
            onboarding_completed=onboarding_completed,
        )


# ---------------------------------------------------------------------------
# Password reset (purpose='reset' OTP)
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class ResetPassword:
    """Consume a ``purpose='reset'`` OTP and set a new password.

    Security invariants (all enforced; failure of any one = atomic abort):

    1. The user whose ``password_hash`` is updated is *exactly* the owner of
       the OTP row (``OTP.user_id``). The request body's ``email`` is used
       ONLY as a cross-check — never as the lookup key for the user to
       mutate. Defends against cross-user attacks where an attacker holds a
       victim's OTP and submits their own email hoping the backend mutates
       the wrong row.
    2. The OTP MUST carry a non-null ``user_id``. Reset is only meaningful
       for an existing verified user. A reset request that resolves to a
       ``user_id IS NULL`` OTP (e.g. a stray register OTP) → ``otp_invalid``.
    3. Single-use: the OTP is atomically claimed (``DELETE ... RETURNING``).
       Two concurrent calls quoting the same code → exactly one wins.
    4. After a successful password change, every active refresh token of
       the user is revoked. Any session minted with the previous credential
       (including the attacker's, if the reset was triggered by a
       takeover-in-progress) loses its rotation capability immediately.
    5. Anti-enumeration: when no active reset OTP exists for the email, the
       caller observes the same outcome as a successful reset (silent 204
       at the router boundary — the use case returns normally). We do NOT
       emit ``NotFoundError`` here. The router maps the silent path.
    6. PII: no email plaintext in logs. ``user_id_hash`` is sha256[:16].
    """

    users: UserRepository
    otps: OtpRepository
    refresh_tokens: RefreshTokenRepository
    hasher: PasswordHasher

    async def __call__(self, *, email: str, code: str, new_password: str) -> None:
        normalized = Email(email).normalized

        # (1) Backend-side password policy. Re-validated here so the use
        # case is the single source of truth for the rule even when the
        # presentation layer's Pydantic schema is bypassed (e.g. internal
        # invocations, scripted recovery). Matches ``RegisterUser`` policy.
        if len(new_password) < 8:
            raise BusinessRuleViolation("weak_password")

        # (2) Lookup the active reset OTP by email. Use the email-keyed
        # lookup (NOT user_id-keyed) so we never even resolve a ``users``
        # row from the request body's email before we have an OTP — which
        # would otherwise leak account existence via timing.
        otp = await self.otps.get_active_by_email(normalized, "reset")
        if otp is None:
            # Silent path (router → 204). Anti-enumeration: indistinguishable
            # from a successful reset for an attacker probing emails. We log
            # for ops observability but never expose externally.
            _log.info("password.reset_silent_no_otp")
            return

        now = _now()
        if otp.is_locked(now):
            # An OTP can be locked-out due to too many wrong attempts on
            # /auth/otp/verify. Refuse the reset.
            raise LockedError("otp_locked")
        if otp.expires_at <= now:
            raise BusinessRuleViolation("otp_expired")

        # (3) Reset OTPs MUST carry a user_id. Register OTPs are the only
        # purpose allowed to be user-less and they should never match the
        # purpose='reset' query, but defence-in-depth: if somehow a row
        # arrives here without user_id, refuse — never mutate "the matching
        # user by email" because that bypasses the OTP→user binding.
        if otp.user_id is None:
            _log.warning("password.reset_otp_user_id_null", otp_id=str(otp.id))
            raise InvalidCredentials("otp_invalid")

        # (4) Verify the submitted code BEFORE looking up the user — extra
        # mutation-blocking gate. Failed attempts increment the OTP's
        # attempt counter exactly like /auth/otp/verify so brute-force gets
        # the same lockout treatment.
        if not self.hasher.verify(code, otp.code_hash):
            attempts = await self.otps.increment_attempts(otp.id)
            if attempts >= OTP_MAX_ATTEMPTS:
                await self.otps.lock(otp.id, now + OTP_LOCK_DURATION)
                raise LockedError("otp_locked")
            raise InvalidCredentials("otp_invalid")

        # (5) Load the user the OTP is bound to. user_id wins over any
        # email present in the request body.
        user = await self.users.get_by_id(otp.user_id)
        if user is None or user.is_deleted:
            # User vanished between OTP issue and consumption (account
            # deletion, hard delete, etc). Refuse — same 401 surface, no
            # distinct error code that would leak.
            raise InvalidCredentials("otp_invalid")

        # (6) Cross-user defence: the request body's email MUST match the
        # email on the user record bound to the OTP. An attacker who somehow
        # learned a victim's OTP cannot submit it with their own email to
        # take over a row they own — the mismatch trips here and the
        # password is not mutated.
        if user.email != normalized:
            _log.warning(
                "password.reset_email_mismatch",
                user_id_hash=_hash_user_id(user.id),
            )
            raise InvalidCredentials("otp_invalid")

        # (7) Atomic single-use claim of the OTP. Two concurrent calls with
        # the same OTP code: only one wins. Loser → 401.
        won = await self.otps.claim(otp.id)
        if not won:
            raise InvalidCredentials("otp_invalid")

        # (8) Mutate password + revoke every active refresh token. SAME
        # SQLAlchemy session as everything above → ONE transaction → all
        # changes commit together or roll back together. Order matters: if
        # revoke_all_for_user fails after the password is updated, the
        # outer route session.rollback also unwinds the password change.
        user.password_hash = self.hasher.hash(new_password)
        await self.users.update(user)
        await self.refresh_tokens.revoke_all_for_user(user.id, now)

        # (9) Audit. PII-safe — no email, no password, only user_id_hash.
        _log.info(
            "password.reset_completed",
            user_id_hash=_hash_user_id(user.id),
        )


def _hash_user_id(user_id: UUID) -> str:
    import hashlib

    return hashlib.sha256(str(user_id).encode()).hexdigest()[:16]


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
