"""SQLAlchemy async repository implementations for identity."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.identity.domain.entities import OtpCode, OtpPurpose, RefreshToken, User
from app.identity.infrastructure.models import OtpCodeModel, RefreshTokenModel, UserModel


def _user_from_model(m: UserModel) -> User:
    return User(
        id=m.id,
        email=m.email,
        password_hash=m.password_hash,
        oauth_provider=m.oauth_provider,
        oauth_subject=m.oauth_subject,
        email_verified=m.email_verified,
        role=m.role,
        created_at=m.created_at,
        last_login_at=m.last_login_at,
        deletion_requested_at=m.deletion_requested_at,
        deleted_at=m.deleted_at,
    )


def _token_from_model(m: RefreshTokenModel) -> RefreshToken:
    return RefreshToken(
        id=m.id,
        user_id=m.user_id,
        token_hash=m.token_hash,
        family_id=m.family_id,
        parent_id=m.parent_id,
        expires_at=m.expires_at,
        revoked_at=m.revoked_at,
        reused_at=m.reused_at,
        created_at=m.created_at,
    )


def _otp_from_model(m: OtpCodeModel) -> OtpCode:
    return OtpCode(
        id=m.id,
        user_id=m.user_id,
        email=m.email,
        password_hash=m.password_hash,
        code_hash=m.code_hash,
        purpose=m.purpose,  # type: ignore[arg-type]
        expires_at=m.expires_at,
        attempts=m.attempts,
        locked_until=m.locked_until,
        created_at=m.created_at,
    )


class SqlUserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.s = session

    async def get_by_id(self, user_id: UUID) -> User | None:
        m = await self.s.get(UserModel, user_id)
        return _user_from_model(m) if m else None

    async def get_by_email(self, email: str) -> User | None:
        m = (
            await self.s.execute(select(UserModel).where(UserModel.email == email))
        ).scalar_one_or_none()
        return _user_from_model(m) if m else None

    async def get_by_oauth(self, provider: str, subject: str) -> User | None:
        stmt = select(UserModel).where(
            UserModel.oauth_provider == provider,
            UserModel.oauth_subject == subject,
        )
        m = (await self.s.execute(stmt)).scalar_one_or_none()
        return _user_from_model(m) if m else None

    async def add(self, user: User) -> None:
        self.s.add(
            UserModel(
                id=user.id,
                email=user.email,
                password_hash=user.password_hash,
                oauth_provider=user.oauth_provider,
                oauth_subject=user.oauth_subject,
                email_verified=user.email_verified,
                role=user.role,
                created_at=user.created_at,
            )
        )
        await self.s.flush()

    async def update(self, user: User) -> None:
        await self.s.execute(
            update(UserModel)
            .where(UserModel.id == user.id)
            .values(
                email=user.email,
                password_hash=user.password_hash,
                oauth_provider=user.oauth_provider,
                oauth_subject=user.oauth_subject,
                email_verified=user.email_verified,
                role=user.role,
                last_login_at=user.last_login_at,
                deletion_requested_at=user.deletion_requested_at,
                deleted_at=user.deleted_at,
            )
        )

    async def schedule_deletion(self, user_id: UUID, scheduled_for: datetime) -> None:
        await self.s.execute(
            update(UserModel)
            .where(UserModel.id == user_id)
            .values(deletion_requested_at=scheduled_for),
        )

    async def cancel_deletion(self, user_id: UUID) -> None:
        await self.s.execute(
            update(UserModel).where(UserModel.id == user_id).values(deletion_requested_at=None),
        )

    async def hard_delete(self, user_id: UUID) -> None:
        # All owned tables cascade. audit_log uses SET NULL (preserves trace).
        await self.s.execute(text("DELETE FROM users WHERE id = :id"), {"id": user_id})

    async def get_onboarding_completed(self, user_id: UUID) -> bool:
        # Cross-context read of `user_profiles.onboarding_completed`. Plain
        # text() (no ORM import of UserProfileModel) keeps identity from
        # taking a hard dependency on profile's SQLAlchemy mappers.
        # COALESCE → False when the profile row does not exist yet.
        row = (
            await self.s.execute(
                text(
                    "SELECT COALESCE(onboarding_completed, FALSE) "
                    "FROM user_profiles WHERE user_id = :uid"
                ),
                {"uid": str(user_id)},
            )
        ).first()
        return bool(row[0]) if row is not None else False


class SqlRefreshTokenRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.s = session

    async def add(self, token: RefreshToken) -> None:
        self.s.add(
            RefreshTokenModel(
                id=token.id,
                user_id=token.user_id,
                token_hash=token.token_hash,
                family_id=token.family_id,
                parent_id=token.parent_id,
                expires_at=token.expires_at,
                revoked_at=token.revoked_at,
                reused_at=token.reused_at,
                created_at=token.created_at,
            )
        )
        await self.s.flush()

    async def get_by_hash(self, token_hash: str) -> RefreshToken | None:
        m = (
            await self.s.execute(
                select(RefreshTokenModel).where(RefreshTokenModel.token_hash == token_hash)
            )
        ).scalar_one_or_none()
        return _token_from_model(m) if m else None

    async def revoke(self, token_id: UUID, at: datetime) -> None:
        await self.s.execute(
            update(RefreshTokenModel).where(RefreshTokenModel.id == token_id).values(revoked_at=at),
        )

    async def revoke_family(self, family_id: UUID, at: datetime) -> int:
        res = await self.s.execute(
            update(RefreshTokenModel)
            .where(
                RefreshTokenModel.family_id == family_id,
                RefreshTokenModel.revoked_at.is_(None),
            )
            .values(revoked_at=at),
        )
        return res.rowcount or 0

    async def mark_reused(self, token_id: UUID, at: datetime) -> None:
        await self.s.execute(
            update(RefreshTokenModel).where(RefreshTokenModel.id == token_id).values(reused_at=at),
        )


class SqlOtpRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.s = session

    async def add(self, otp: OtpCode) -> None:
        # QA: invalidate any pre-existing active OTP for the same
        # (user_id|email, purpose) BEFORE inserting the new row. Without
        # this, every /auth/otp/send leaves stale codes that
        # ``get_active_by_email`` (ORDER BY created_at DESC LIMIT 1) hides,
        # and a future UNIQUE constraint addition would 500 on insert.
        # Idempotent + bounded — deletes only the matching purpose rows
        # already past usefulness (newer OTP supersedes them).
        if otp.user_id is not None:
            await self.s.execute(
                text(
                    "DELETE FROM otp_codes "
                    "WHERE user_id = :uid AND purpose = :p"
                ),
                {"uid": otp.user_id, "p": otp.purpose},
            )
        elif otp.email is not None:
            await self.s.execute(
                text(
                    "DELETE FROM otp_codes "
                    "WHERE user_id IS NULL AND email = :em AND purpose = :p"
                ),
                {"em": otp.email, "p": otp.purpose},
            )
        self.s.add(
            OtpCodeModel(
                id=otp.id,
                user_id=otp.user_id,
                email=otp.email,
                password_hash=otp.password_hash,
                code_hash=otp.code_hash,
                purpose=otp.purpose,
                expires_at=otp.expires_at,
                attempts=otp.attempts,
                locked_until=otp.locked_until,
                created_at=otp.created_at,
            )
        )
        await self.s.flush()

    async def get_active(self, user_id: UUID, purpose: OtpPurpose) -> OtpCode | None:
        stmt = (
            select(OtpCodeModel)
            .where(
                OtpCodeModel.user_id == user_id,
                OtpCodeModel.purpose == purpose,
            )
            .order_by(OtpCodeModel.created_at.desc())
            .limit(1)
        )
        m = (await self.s.execute(stmt)).scalar_one_or_none()
        return _otp_from_model(m) if m else None

    async def get_active_by_email(self, email: str, purpose: OtpPurpose) -> OtpCode | None:
        stmt = (
            select(OtpCodeModel)
            .where(
                OtpCodeModel.email == email,
                OtpCodeModel.purpose == purpose,
            )
            .order_by(OtpCodeModel.created_at.desc())
            .limit(1)
        )
        m = (await self.s.execute(stmt)).scalar_one_or_none()
        return _otp_from_model(m) if m else None

    async def increment_attempts(self, otp_id: UUID) -> int:
        res = await self.s.execute(
            update(OtpCodeModel)
            .where(OtpCodeModel.id == otp_id)
            .values(attempts=OtpCodeModel.attempts + 1)
            .returning(OtpCodeModel.attempts),
        )
        row = res.first()
        return int(row[0]) if row else 0

    async def lock(self, otp_id: UUID, until: datetime) -> None:
        await self.s.execute(
            update(OtpCodeModel).where(OtpCodeModel.id == otp_id).values(locked_until=until),
        )

    async def consume(self, otp_id: UUID) -> None:
        # Consumption = delete (one-shot semantics).
        await self.s.execute(text("DELETE FROM otp_codes WHERE id = :id"), {"id": otp_id})
