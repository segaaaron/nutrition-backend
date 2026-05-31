"""Push token registration router."""
from __future__ import annotations

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, status
from pydantic import BaseModel
from sqlalchemy import text

from app.identity.presentation.dependencies import CurrentUserDep, SessionDep

router = APIRouter(prefix="/push", tags=["notifications"])


class RegisterTokenRequest(BaseModel):
    platform: Literal["web", "ios", "android"]
    token: str
    endpoint: str | None = None
    p256dh: str | None = None
    auth: str | None = None
    locale: str = "en"


@router.post("/tokens", status_code=status.HTTP_201_CREATED)
async def register_token(
    body: RegisterTokenRequest, current_user: CurrentUserDep, session: SessionDep,
) -> dict:
    await session.execute(text("""
        INSERT INTO push_tokens (user_id, platform, token, endpoint, p256dh, auth, locale, created_at)
        VALUES (:uid, :p, :tok, :ep, :k, :au, :loc, now())
        ON CONFLICT (token) DO UPDATE SET
          user_id = EXCLUDED.user_id,
          platform = EXCLUDED.platform,
          endpoint = EXCLUDED.endpoint,
          p256dh = EXCLUDED.p256dh,
          auth = EXCLUDED.auth,
          locale = EXCLUDED.locale,
          invalid_at = NULL
    """), {
        "uid": str(current_user), "p": body.platform, "tok": body.token,
        "ep": body.endpoint, "k": body.p256dh, "au": body.auth, "loc": body.locale,
    })
    return {"ok": True}


@router.delete("/tokens/{token}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_token(
    token: str, current_user: CurrentUserDep, session: SessionDep,
) -> None:
    await session.execute(text("""
        DELETE FROM push_tokens WHERE token = :t AND user_id = :uid
    """), {"t": token, "uid": str(current_user)})
