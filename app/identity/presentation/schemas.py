"""Pydantic request/response schemas. Strict (`extra='forbid'`)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RegisterRequest(_Strict):
    email: EmailStr = Field(json_schema_extra={"example": "miguel@example.com"})
    password: str = Field(
        min_length=8, json_schema_extra={"example": "correct horse battery staple"}
    )


class LoginRequest(_Strict):
    email: EmailStr
    password: str


class OAuthLoginRequest(_Strict):
    id_token: str = Field(min_length=20)


class RefreshRequest(_Strict):
    refresh_token: str = Field(min_length=32)


class LogoutRequest(_Strict):
    refresh_token: str = Field(min_length=32)


class SendOtpRequest(_Strict):
    email: EmailStr
    purpose: Literal["register", "reset", "login"]


class VerifyOtpRequest(_Strict):
    email: EmailStr
    purpose: Literal["register", "reset", "login"]
    code: str = Field(min_length=6, max_length=6)


class RegisterPendingResponse(_Strict):
    status: Literal["pending_verification"] = "pending_verification"


class TokenPairResponse(_Strict):
    access_token: str
    refresh_token: str
    token_type: Literal["bearer"] = "bearer"
    user_id: UUID
    # Rollback symmetry (QA R2): field has a default, so a backend rollback
    # to a version without the column read keeps the response valid for new
    # iOS clients (Swift `decodeIfPresent ?? false`). Old iOS clients tolerate
    # the extra field per Codable default behaviour. Both directions safe.
    onboarding_completed: bool = False


class DeletionScheduledResponse(_Strict):
    status: Literal["scheduled"] = "scheduled"
    scheduled_for: datetime


class CancellationResponse(_Strict):
    cancelled: bool = True


class ExportResponse(_Strict):
    user: dict
    note: str
