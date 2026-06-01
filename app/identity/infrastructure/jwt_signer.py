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

# ---------------------------------------------------------------------------
# Redis JWT revocation denylist
# ---------------------------------------------------------------------------

_DENYLIST_PREFIX = "jwt:denylist:"


async def revoke_jti(jti: str, *, ttl_seconds: int) -> None:
    """Add jti to Redis denylist with TTL matching access token lifetime.

    Entry expires when the token would have expired anyway — no memory leak.
    """
    from app.core.redis import get_redis
    r = get_redis()
    await r.set(f"{_DENYLIST_PREFIX}{jti}", "1", ex=ttl_seconds)


async def is_jti_revoked(jti: str) -> bool:
    """Return True if the jti is present in the Redis denylist."""
    from app.core.redis import get_redis
    r = get_redis()
    return (await r.exists(f"{_DENYLIST_PREFIX}{jti}")) > 0


# ---------------------------------------------------------------------------
# Signer
# ---------------------------------------------------------------------------

class JwtSigner:
    def __init__(self) -> None:
        s = get_settings()
        self._issuer = s.jwt_issuer
        self._audience = s.jwt_audience
        self._access_ttl = s.jwt_access_ttl_seconds
        self._active_kid = s.jwt_active_kid
        self._revoked: set[str] = {
            k.strip() for k in s.jwt_revoked_kids.split(",") if k.strip()
        }
        self._keys: dict[str, tuple[bytes, bytes]] = {}  # kid -> (priv_pem, pub_pem)

        if s.jwt_signing_keys:
            # Multi-key path: "k1:/secrets/v1.pem,k2:/secrets/v2.pem"
            for entry in s.jwt_signing_keys.split(","):
                kid, path = entry.split(":", 1)
                kid = kid.strip()
                path = path.strip()
                priv_path = Path(path)
                pub_path = Path(path.replace(".pem", ".pub"))
                priv = priv_path.read_bytes() if priv_path.exists() else b""
                pub = pub_path.read_bytes() if pub_path.exists() else b""
                self._keys[kid] = (priv, pub)
        else:
            # Legacy single-key path — backward compat for existing tests/deployments
            priv_path = Path(s.jwt_private_key_path)
            pub_path = Path(s.jwt_public_key_path)
            priv = priv_path.read_bytes() if priv_path.exists() else b""
            pub = pub_path.read_bytes() if pub_path.exists() else b""
            self._keys[self._active_kid] = (priv, pub)

    def sign_access(self, *, user_id: UUID, role: str) -> str:
        priv, _ = self._keys[self._active_kid]
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
        return pyjwt.encode(
            payload, priv, algorithm="RS256", headers={"kid": self._active_kid}
        )

    async def verify_access(self, token: str) -> dict:
        """Verify RS256 token: check kid, select matching pubkey, check denylist.

        Raises Unauthenticated if:
        - token header is malformed / missing kid
        - kid is in the revoked set
        - kid is unknown (not in key registry)
        - RS256 signature / claims validation fails
        - jti is in Redis denylist
        """
        try:
            unverified_header = pyjwt.get_unverified_header(token)
        except InvalidTokenError as e:
            raise Unauthenticated(f"jwt_invalid:{e!s}") from e

        kid = unverified_header.get("kid")
        if not kid:
            raise Unauthenticated("jwt_missing_kid")
        if kid in self._revoked:
            raise Unauthenticated(f"jwt_kid_revoked:{kid}")
        if kid not in self._keys:
            raise Unauthenticated(f"jwt_kid_unknown:{kid}")

        _, pub = self._keys[kid]
        try:
            claims = pyjwt.decode(
                token,
                pub,
                algorithms=["RS256"],
                audience=self._audience,
                issuer=self._issuer,
                options={"require": ["exp", "iat", "sub", "aud", "iss", "jti"]},
            )
        except InvalidTokenError as e:
            raise Unauthenticated(f"jwt_invalid:{e!s}") from e

        jti = claims.get("jti")
        if jti and await is_jti_revoked(jti):
            raise Unauthenticated("jwt_revoked")
        return claims

    def sign_refresh_value(self) -> str:
        # Opaque, high-entropy. 256 bits.
        return secrets.token_urlsafe(48)

    def hash_refresh(self, plain: str) -> str:
        return hashlib.sha256(plain.encode("utf-8")).hexdigest()
