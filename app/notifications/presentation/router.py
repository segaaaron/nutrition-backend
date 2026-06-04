"""Push token registration router (mobile-only: iOS/Android via FCM).

Web Push was removed 2026-06-04 — NOVA backend serves mobile apps only, no PWA.
Legacy `push_tokens` rows with `platform='web'` remain in DB (dead, dropped next
migration cycle) but are no longer accepted by the registration endpoint.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Response, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import text

from app.identity.presentation.dependencies import CurrentUserDep, SessionDep

router = APIRouter(prefix="/push", tags=["notifications"])


class RegisterTokenRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    platform: Literal["ios", "android"]
    token: str
    locale: str = "en"


@router.post("/tokens", status_code=status.HTTP_201_CREATED)
async def register_token(
    body: RegisterTokenRequest,
    current_user: CurrentUserDep,
    session: SessionDep,
) -> dict:
    await session.execute(
        text(
            """
        INSERT INTO push_tokens (user_id, platform, token, locale, created_at)
        VALUES (:uid, :p, :tok, :loc, now())
        ON CONFLICT (token) DO UPDATE SET
          user_id = EXCLUDED.user_id,
          platform = EXCLUDED.platform,
          locale = EXCLUDED.locale,
          invalid_at = NULL
    """
        ),
        {
            "uid": str(current_user),
            "p": body.platform,
            "tok": body.token,
            "loc": body.locale,
        },
    )
    return {"ok": True}


@router.delete("/tokens/{token}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_token(
    token: str,
    current_user: CurrentUserDep,
    session: SessionDep,
) -> Response:
    # BOLA OK: DELETE WHERE token = :t AND user_id = :uid — silently no-ops if not owner.
    await session.execute(
        text(
            """
        DELETE FROM push_tokens WHERE token = :t AND user_id = :uid
    """
        ),
        {"t": token, "uid": str(current_user)},
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
