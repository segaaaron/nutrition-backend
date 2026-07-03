"""FastAPI router for identity endpoints (/auth/*, /me/{delete,cancel-deletion,export})."""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, Path, Request, Response, status
from sqlalchemy import select

from app.core.config import get_settings
from app.core.logging import get_logger
from app.identity.application.use_cases import (
    CancelDeletion,
    DeleteAccount,
    ExportData,
    LoginUser,
    Logout,
    OAuthLogin,
    RefreshTokens,
    RegisterUser,
    ResetPassword,
    SendOtp,
    VerifyOtp,
)
from app.identity.domain.value_objects import Email
from app.identity.infrastructure.models import UserModel
from app.identity.infrastructure.rate_limit import rate_limit
from app.identity.presentation.dependencies import (
    CurrentUserDep,
    SessionDep,
    make_cancel_delete,
    make_delete,
    make_export,
    make_login,
    make_logout,
    make_oauth,
    make_refresh,
    make_register,
    make_reset_password,
    make_send_otp,
    make_verify_otp,
)
from app.identity.presentation.schemas import (
    CancellationResponse,
    DeletionScheduledResponse,
    ExportResponse,
    LoginRequest,
    LogoutRequest,
    OAuthLoginRequest,
    PasswordResetRequest,
    RefreshRequest,
    RegisterPendingResponse,
    RegisterRequest,
    SendOtpRequest,
    TokenPairResponse,
    VerifyOtpRequest,
)
from app.profile.infrastructure.models import UserProfileModel
from app.shared.i18n import Locale, resolve_email_locale

log = get_logger("identity.router")
router = APIRouter(tags=["auth"])


async def _optional_bearer(request: Request) -> str | None:
    """Extract Bearer token from Authorization header without requiring it."""
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip() or None
    return None


def _token_resp(pair) -> TokenPairResponse:
    return TokenPairResponse(
        access_token=pair.access,
        refresh_token=pair.refresh,
        user_id=pair.user_id,
        onboarding_completed=pair.onboarding_completed,
    )


# ---------------- /auth/* ----------------


@router.post(
    "/auth/register",
    response_model=RegisterPendingResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def register(
    body: RegisterRequest,
    session: SessionDep,
    accept_language: Annotated[str | None, Header(alias="Accept-Language")] = None,
) -> RegisterPendingResponse:
    await rate_limit(
        scope="auth", identifier=body.email, limit_per_min=get_settings().rate_limit_auth_per_min
    )
    locale = await _resolve_otp_email_locale(
        session, email=body.email, accept_language=accept_language
    )
    uc: RegisterUser = make_register(session, locale=locale)
    await uc(email=body.email, password=body.password)
    return RegisterPendingResponse()


@router.post("/auth/login", response_model=TokenPairResponse)
async def login(
    body: LoginRequest,
    session: SessionDep,
) -> TokenPairResponse:
    await rate_limit(
        scope="auth", identifier=body.email, limit_per_min=get_settings().rate_limit_auth_per_min
    )
    uc: LoginUser = make_login(session)
    pair = await uc(email=body.email, password=body.password)
    return _token_resp(pair)


@router.post("/auth/oauth/{provider}", response_model=TokenPairResponse)
async def oauth_login(
    provider: Annotated[Literal["google", "apple"], Path()],
    body: OAuthLoginRequest,
    session: SessionDep,
) -> TokenPairResponse:
    await rate_limit(
        scope="auth",
        identifier=f"oauth:{provider}",
        limit_per_min=get_settings().rate_limit_auth_per_min,
    )
    uc: OAuthLogin = make_oauth(session, provider)
    pair = await uc(id_token=body.id_token)
    return _token_resp(pair)


@router.post("/auth/refresh", response_model=TokenPairResponse)
async def refresh(
    body: RefreshRequest,
    session: SessionDep,
) -> TokenPairResponse:
    uc: RefreshTokens = make_refresh(session)
    pair = await uc(refresh_plain=body.refresh_token)
    return _token_resp(pair)


@router.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    body: LogoutRequest,
    session: SessionDep,
    authorization: Annotated[str | None, Depends(_optional_bearer)],
) -> Response:
    uc: Logout = make_logout(session)
    await uc(refresh_plain=body.refresh_token, access_token=authorization)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


async def _resolve_otp_email_locale(
    session: SessionDep,
    *,
    email: str,
    accept_language: str | None,
) -> Locale:
    """Resolve email locale for OTP dispatch per D5.

    Rule (D5, see ``app.shared.i18n.resolve_email_locale``):

    1. ``profile.locale`` if the user exists AND has a profile row.
    2. First supported tag in ``Accept-Language``.
    3. ``"es"`` default (D4).

    Implementation note: we issue ONE focused ``SELECT locale FROM
    user_profiles WHERE user_id = (SELECT id FROM users WHERE email = ?)``
    style two-step. Cost = at most 2 lightweight indexed lookups. Anon
    signup paths skip both queries entirely once we discover the user is
    missing. No N+1, no cross-context coupling beyond two read-only joins.
    """
    profile_locale: str | None = None
    normalized = Email(email).normalized
    user_id_row = await session.execute(
        select(UserModel.id).where(UserModel.email == normalized)
    )
    user_id = user_id_row.scalar_one_or_none()
    if user_id is not None:
        loc_row = await session.execute(
            select(UserProfileModel.locale).where(
                UserProfileModel.user_id == user_id
            )
        )
        profile_locale = loc_row.scalar_one_or_none()
    return resolve_email_locale(profile_locale, accept_language)


@router.post("/auth/otp/send", status_code=status.HTTP_202_ACCEPTED)
async def otp_send(
    body: SendOtpRequest,
    session: SessionDep,
    accept_language: Annotated[
        str | None, Header(alias="Accept-Language")
    ] = None,
) -> dict:
    await rate_limit(
        scope="auth",
        identifier=f"otp:{body.email}",
        limit_per_min=get_settings().rate_limit_auth_per_min,
    )
    # Hourly cap per email: max 3 OTP requests/hour regardless of per-minute quota.
    # Prevents attackers from generating many OTPs across multiple minutes to
    # brute-force one that hasn't expired (OTP TTL=10min, 6 windows/hour).
    await rate_limit(
        scope="otp_hourly",
        identifier=body.email,
        limit_per_min=3,
        window_s=3600,
    )
    locale = await _resolve_otp_email_locale(
        session, email=body.email, accept_language=accept_language
    )
    uc: SendOtp = make_send_otp(session, locale=locale)
    code = await uc(email=body.email, purpose=body.purpose)
    # Dev mode echoes the code so QA can test without an email worker.
    if get_settings().env == "dev":
        return {"status": "sent", "dev_code": code}
    return {"status": "sent"}


@router.post(
    "/auth/password/reset",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={
        204: {"description": "Password updated, or silently ignored if email unknown."},
        401: {"description": "OTP invalid, expired or locked."},
        422: {"description": "Password does not meet server policy."},
        429: {"description": "Rate limit exceeded."},
    },
)
async def password_reset(
    body: PasswordResetRequest,
    request: Request,
    session: SessionDep,
) -> Response:
    """Consume a ``purpose='reset'`` OTP and rotate the user password.

    Security contract (defended by ``ResetPassword`` use case + this router):

    - Rate limited per-email AND per-IP (composite identifier) so attackers
      cannot bypass throttling either by spraying IPs against one account
      OR by spraying accounts from one IP.
    - 204 on success AND on unknown email (anti-enumeration). The use case
      returns ``None`` for both paths.
    - 401 ``otp_invalid`` / ``otp_expired`` / ``otp_locked`` — uniform code
      space, no distinction between "OTP wrong", "email mismatch on the
      OTP-bound user", or "user vanished".
    - 422 ``weak_password`` — backend policy re-applied (defence-in-depth
      vs. the Pydantic schema rule).
    - No tokens emitted: the client logs in via ``POST /auth/login`` after
      a successful reset. Sessions in flight before the reset are revoked.
    """
    client_ip = request.client.host if request.client else "unknown"
    # Composite rate-limit identifier: ties both axes together so a single
    # bucket counts (email, ip) pairs. An attacker pivoting either axis
    # alone still trips the bucket on the unchanged axis.
    await rate_limit(
        scope="auth",
        identifier=f"pwreset:{body.email}:{client_ip}",
        limit_per_min=get_settings().rate_limit_auth_per_min,
    )
    uc: ResetPassword = make_reset_password(session)
    await uc(email=body.email, code=body.code, new_password=body.new_password)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/auth/otp/verify", response_model=TokenPairResponse)
async def otp_verify(
    body: VerifyOtpRequest,
    session: SessionDep,
) -> TokenPairResponse:
    await rate_limit(
        scope="auth",
        identifier=f"otpverify:{body.email}",
        limit_per_min=get_settings().rate_limit_auth_per_min,
    )
    uc: VerifyOtp = make_verify_otp(session)
    pair = await uc(email=body.email, purpose=body.purpose, code=body.code)
    return _token_resp(pair)


# ---------------- /me/* (GDPR) ----------------


@router.delete(
    "/me", response_model=DeletionScheduledResponse, status_code=status.HTTP_202_ACCEPTED
)
async def delete_account(
    current_user: CurrentUserDep,
    session: SessionDep,
) -> DeletionScheduledResponse:
    uc: DeleteAccount = make_delete(session)
    scheduled_for = await uc(user_id=current_user)
    return DeletionScheduledResponse(scheduled_for=scheduled_for)


@router.post("/me/cancel-deletion", response_model=CancellationResponse)
async def cancel_deletion(
    current_user: CurrentUserDep,
    session: SessionDep,
) -> CancellationResponse:
    uc: CancelDeletion = make_cancel_delete(session)
    await uc(user_id=current_user)
    return CancellationResponse()


@router.get("/me/export", response_model=ExportResponse)
async def export_data(
    current_user: CurrentUserDep,
    session: SessionDep,
) -> ExportResponse:
    uc: ExportData = make_export(session)
    blob = await uc(user_id=current_user)
    return ExportResponse(**blob)
