"""RS256 JWT signer/verifier backed by PyJWT.

Migrated from python-jose (2026-06): jose is semi-abandoned and accrues
CVEs. PyJWT is the mainstream maintained alternative; same RS256 keys
work without rotation.
"""
from __future__ import annotations

import hashlib
import secrets
import time
from pathlib import Path
from uuid import UUID, uuid4

import jwt as pyjwt
from jwt.exceptions import InvalidTokenError

from app.core.config import get_settings
from app.core.errors import Unauthenticated


class JwtSigner:
    def __init__(self) -> None:
        s = get_settings()
        self._issuer = s.jwt_issuer
        self._audience = s.jwt_audience
        self._access_ttl = s.jwt_access_ttl_seconds
        priv_path = Path(s.jwt_private_key_path)
        pub_path = Path(s.jwt_public_key_path)
        self._private_key = priv_path.read_bytes() if priv_path.exists() else b""
        self._public_key = pub_path.read_bytes() if pub_path.exists() else b""

    def sign_access(self, *, user_id: UUID, role: str) -> str:
        now = int(time.time())
        payload = {
            "sub": str(user_id),
            "role": role,
            "iss": self._issuer,
            "aud": self._audience,
            "iat": now,
            "exp": now + self._access_ttl,
            "jti": uuid4().hex,
        }
        return pyjwt.encode(payload, self._private_key, algorithm="RS256")

    def verify_access(self, token: str) -> dict:
        try:
            return pyjwt.decode(
                token,
                self._public_key,
                algorithms=["RS256"],
                audience=self._audience,
                issuer=self._issuer,
                options={"require": ["exp", "iat", "sub", "aud", "iss"]},
            )
        except InvalidTokenError as e:
            raise Unauthenticated(f"jwt_invalid:{e!s}") from e

    def sign_refresh_value(self) -> str:
        # Opaque, high-entropy. 256 bits.
        return secrets.token_urlsafe(48)

    def hash_refresh(self, plain: str) -> str:
        return hashlib.sha256(plain.encode("utf-8")).hexdigest()
