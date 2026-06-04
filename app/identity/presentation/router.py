"""FastAPI router for identity endpoints (/auth/*, /me/{delete,cancel-deletion,export})."""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Path, Request, Response, status

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
    SendOtp,
    VerifyOtp,
)
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
    RefreshRequest,
    RegisterRequest,
    SendOtpRequest,
    TokenPairResponse,
    VerifyOtpRequest,
)

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
    )


# ---------------- /auth/* ----------------


@router.post(
    "/auth/register", response_model=TokenPairResponse, status_code=status.HTTP_201_CREATED
)
async def register(
    body: RegisterRequest,
    session: SessionDep,
) -> TokenPairResponse:
    await rate_limit(
        scope="auth", identifier=body.email, limit_per_min=get_settings().rate_limit_auth_per_min
    )
    uc: RegisterUser = make_register(session)
    pair = await uc(email=body.email, password=body.password)
    return _token_resp(pair)


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


@router.post("/auth/otp/send", status_code=status.HTTP_202_ACCEPTED)
async def otp_send(
    body: SendOtpRequest,
    session: SessionDep,
) -> dict:
    await rate_limit(
        scope="auth",
        identifier=f"otp:{body.email}",
        limit_per_min=get_settings().rate_limit_auth_per_min,
    )
    uc: SendOtp = make_send_otp(session)
    code = await uc(email=body.email, purpose=body.purpose)
    # Dev mode echoes the code so QA can test without an email worker.
    if get_settings().env == "dev":
        return {"status": "sent", "dev_code": code}
    return {"status": "sent"}


@router.post("/auth/otp/verify", response_model=TokenPairResponse)
async def otp_verify(
    body: VerifyOtpRequest,
    session: SessionDep,
) -> TokenPairResponse:
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
