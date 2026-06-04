"""Google + Apple ID-token verifiers.

For MVP we keep verification minimal but correct: pull JWKS, verify signature,
issuer, audience, and expiry. Apple revocation handling (POST to apple's
revocation endpoint on logout) is documented as a TODO — Apple Sign-in flow
in the iOS client carries it for now.
"""

from __future__ import annotations

from typing import Any

import httpx
import jwt as pyjwt
from jwt.algorithms import RSAAlgorithm

from app.core.config import get_settings
from app.core.errors import Unauthenticated


class _BaseOAuthVerifier:
    JWKS_URL: str
    ISSUERS: tuple[str, ...]

    def __init__(self, audience: str) -> None:
        self._audience = audience
        self._jwks: list[dict[str, Any]] | None = None

    async def _fetch_jwks(self) -> list[dict[str, Any]]:
        if self._jwks is None:
            async with httpx.AsyncClient(timeout=5) as client:
                resp = await client.get(self.JWKS_URL)
                resp.raise_for_status()
                self._jwks = resp.json()["keys"]
        return self._jwks  # type: ignore[return-value]

    async def verify_id_token(self, id_token: str) -> dict:
        try:
            headers = pyjwt.get_unverified_header(id_token)
            kid = headers.get("kid")
            keys = await self._fetch_jwks()
            key_data = next((k for k in keys if k.get("kid") == kid), None)
            if key_data is None:
                raise Unauthenticated("oauth_unknown_kid")
            import json

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

    def __init__(self) -> None:
        super().__init__(audience=get_settings().google_oauth_client_id)


class AppleOAuthVerifier(_BaseOAuthVerifier):
    JWKS_URL = "https://appleid.apple.com/auth/keys"
    ISSUERS = ("https://appleid.apple.com",)

    def __init__(self) -> None:
        super().__init__(audience=get_settings().apple_oauth_client_id)

    # TODO(apple-revocation): POST to https://appleid.apple.com/auth/revoke
    # on Logout / DeleteAccount with a client_secret JWT signed by the team's
    # ES256 key. Ops runbook lives in docs/ops/apple-signin.md (to author).
