"""Google + Apple ID-token verifiers.

JWKS are cached in Redis (key ``jwks:{provider}``, TTL 6 h) so every OAuth
login does not make a live HTTPS call to Google/Apple. A Redis miss falls back
to the JWKS endpoint and repopulates the cache.

Apple revocation (POST /auth/revoke on logout/delete) requires storing Apple's
refresh token at login time, which needs a DB column. Tracked in
docs/product/gaps/apple-revocation.md — not yet implemented.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import httpx
import jwt as pyjwt
from jwt.algorithms import RSAAlgorithm

from app.core.config import get_settings
from app.core.errors import Unauthenticated

if TYPE_CHECKING:
    from redis.asyncio import Redis

# Shared JWKS cache TTL. Long enough to avoid hammering Google/Apple on every
# login; short enough to pick up key rotations within the day.
_JWKS_TTL_SECONDS = 6 * 3600  # 6 hours


class _BaseOAuthVerifier:
    JWKS_URL: str
    ISSUERS: tuple[str, ...]
    # Redis key used for this provider's JWKS cache.
    _REDIS_KEY: str

    def __init__(self, audience: str, redis: "Redis | None" = None) -> None:
        self._audience = audience
        self._redis = redis

    async def _fetch_jwks(self) -> list[dict[str, Any]]:
        """Return JWKS keys. Redis-cached on hit; live HTTPS fetch on miss."""
        if self._redis is not None:
            cached = await self._redis.get(self._REDIS_KEY)
            if cached:
                return json.loads(cached)  # type: ignore[return-value]

        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(self.JWKS_URL)
            resp.raise_for_status()
            keys: list[dict[str, Any]] = resp.json()["keys"]

        if self._redis is not None:
            await self._redis.setex(self._REDIS_KEY, _JWKS_TTL_SECONDS, json.dumps(keys))

        return keys

    async def verify_id_token(self, id_token: str) -> dict:
        try:
            headers = pyjwt.get_unverified_header(id_token)
            kid = headers.get("kid")
            keys = await self._fetch_jwks()
            key_data = next((k for k in keys if k.get("kid") == kid), None)
            if key_data is None:
                # kid not in cached JWKS — provider may have rotated keys.
                # Bust cache and retry once before giving up.
                if self._redis is not None:
                    await self._redis.delete(self._REDIS_KEY)
                keys = await self._fetch_jwks()
                key_data = next((k for k in keys if k.get("kid") == kid), None)
            if key_data is None:
                raise Unauthenticated("oauth_unknown_kid")
            public_key = RSAAlgorithm.from_jwk(json.dumps(key_data))
            claims: dict = pyjwt.decode(
                id_token,
                public_key,
                algorithms=[key_data.get("alg", "RS256")],
                audience=self._audience,
            )
            if claims.get("iss") not in self.ISSUERS:
                raise Unauthenticated("oauth_bad_issuer")
            return claims
        except Unauthenticated:
            raise
        except Exception as e:  # noqa: BLE001
            raise Unauthenticated(f"oauth_verify_failed:{e!s}") from e


class GoogleOAuthVerifier(_BaseOAuthVerifier):
    JWKS_URL = "https://www.googleapis.com/oauth2/v3/certs"
    ISSUERS = ("https://accounts.google.com", "accounts.google.com")
    _REDIS_KEY = "jwks:google"

    def __init__(self, redis: "Redis | None" = None) -> None:
        super().__init__(audience=get_settings().google_oauth_client_id, redis=redis)


class AppleOAuthVerifier(_BaseOAuthVerifier):
    JWKS_URL = "https://appleid.apple.com/auth/keys"
    ISSUERS = ("https://appleid.apple.com",)
    _REDIS_KEY = "jwks:apple"

    def __init__(self, redis: "Redis | None" = None) -> None:
        super().__init__(audience=get_settings().apple_oauth_client_id, redis=redis)
