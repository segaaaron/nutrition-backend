"""JWT revocation list — Redis denylist tests.

OWASP API2 / ASVS V3: access token must be invalidatable on logout.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from app.core.errors import Unauthenticated


@pytest.fixture
def keypair(monkeypatch, tmp_path):
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    priv = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    priv_pem = priv.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    pub_pem = priv.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    priv_path = tmp_path / "jwt.pem"
    pub_path = tmp_path / "jwt.pub"
    priv_path.write_bytes(priv_pem)
    pub_path.write_bytes(pub_pem)
    monkeypatch.setenv("JWT_PRIVATE_KEY_PATH", str(priv_path))
    monkeypatch.setenv("JWT_PUBLIC_KEY_PATH", str(pub_path))
    from app.core.config import get_settings

    get_settings.cache_clear()
    yield


async def test_revoked_token_rejected(keypair, fake_redis, monkeypatch):
    """Token added to denylist must raise Unauthenticated on verify."""
    from app.core import redis as redis_mod

    monkeypatch.setattr(redis_mod, "get_redis", lambda: fake_redis)

    from app.identity.infrastructure.jwt_signer import JwtSigner, revoke_jti

    signer = JwtSigner()
    token = signer.sign_access(user_id=uuid4(), role="user")
    claims_before = await signer.verify_access(token)

    await revoke_jti(claims_before["jti"], ttl_seconds=60)

    with pytest.raises(Unauthenticated, match="revoked"):
        await signer.verify_access(token)


async def test_non_revoked_token_passes(keypair, fake_redis, monkeypatch):
    """Token not in denylist must verify successfully."""
    from app.core import redis as redis_mod

    monkeypatch.setattr(redis_mod, "get_redis", lambda: fake_redis)

    from app.identity.infrastructure.jwt_signer import JwtSigner

    signer = JwtSigner()
    token = signer.sign_access(user_id=uuid4(), role="user")
    claims = await signer.verify_access(token)
    assert claims["sub"]


async def test_is_jti_revoked_returns_true_when_in_denylist(fake_redis, monkeypatch):
    """is_jti_revoked reflects exact denylist state."""
    from app.core import redis as redis_mod

    monkeypatch.setattr(redis_mod, "get_redis", lambda: fake_redis)

    from app.identity.infrastructure.jwt_signer import is_jti_revoked, revoke_jti

    await revoke_jti("abc123", ttl_seconds=60)
    assert await is_jti_revoked("abc123") is True
    assert await is_jti_revoked("notthere") is False
