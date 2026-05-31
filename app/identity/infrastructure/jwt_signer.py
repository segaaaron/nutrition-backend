"""JWT signing infrastructure. RS256 with `kid` header for key rotation.

For dev / tests, falls back to an in-memory HS256 secret when key files are
absent — production deployment MUST mount RSA key pair via Dokploy secrets.
"""
from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID

from jose import jwt as jose_jwt

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
        if priv_path.exists() and pub_path.exists():
            self._algorithm = "RS256"
            self._private_key = priv_path.read_text()
            self._public_key = pub_path.read_text()
            self._kid = hashlib.sha256(self._public_key.encode()).hexdigest()[:16]
        else:
            # Dev fallback. NEVER use in prod.
            self._algorithm = "HS256"
            self._private_key = secrets.token_urlsafe(48)
            self._public_key = self._private_key
            self._kid = "dev-hs256"

    def sign_access(self, *, user_id: UUID, role: str) -> str:
        now = datetime.now(tz=timezone.utc)
        payload = {
            "sub": str(user_id),
            "role": role,
            "iss": self._issuer,
            "aud": self._audience,
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(seconds=self._access_ttl)).timestamp()),
        }
        return jose_jwt.encode(
            payload, self._private_key, algorithm=self._algorithm,
            headers={"kid": self._kid},
        )

    def verify_access(self, token: str) -> dict:
        try:
            return jose_jwt.decode(
                token, self._public_key,
                algorithms=[self._algorithm],
                audience=self._audience,
                issuer=self._issuer,
            )
        except Exception as e:  # noqa: BLE001
            raise Unauthenticated(f"jwt_invalid:{e!s}") from e

    def sign_refresh_value(self) -> str:
        # Opaque, high-entropy. 256 bits.
        return secrets.token_urlsafe(48)

    def hash_refresh(self, plain: str) -> str:
        return hashlib.sha256(plain.encode("utf-8")).hexdigest()
