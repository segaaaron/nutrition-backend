"""JWT key rotation — kid header tests.

ASVS V2 / S0-J: multiple keypairs, zero-downtime rotation, revoked-kid rejection,
unknown-kid anti-forgery.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from app.core.errors import Unauthenticated


def _gen_key(tmp_path, name: str) -> tuple[str, str]:
    """Generate RSA keypair, write to tmp_path/{name}.pem + .pub, return paths."""
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
    priv_path = tmp_path / f"{name}.pem"
    pub_path = tmp_path / f"{name}.pub"
    priv_path.write_bytes(priv_pem)
    pub_path.write_bytes(pub_pem)
    return str(priv_path), str(pub_path)


@pytest.fixture
def two_keys(monkeypatch, tmp_path):
    """Configure two RSA keypairs (k1, k2). Active kid = k1."""
    k1_priv, _ = _gen_key(tmp_path, "k1")
    k2_priv, _ = _gen_key(tmp_path, "k2")
    monkeypatch.setenv("JWT_SIGNING_KEYS", f"k1:{k1_priv},k2:{k2_priv}")
    monkeypatch.setenv("JWT_ACTIVE_KID", "k1")
    monkeypatch.setenv("JWT_REVOKED_KIDS", "")
    from app.core.config import get_settings

    get_settings.cache_clear()
    yield
    from app.core.config import get_settings as gs

    gs.cache_clear()


async def test_token_carries_active_kid_header(two_keys, fake_redis, monkeypatch):
    """New tokens must embed the active kid in their JOSE header."""
    from app.core import redis as redis_mod

    monkeypatch.setattr(redis_mod, "get_redis", lambda: fake_redis)

    import jwt as pyjwt

    from app.identity.infrastructure.jwt_signer import JwtSigner

    signer = JwtSigner()
    token = signer.sign_access(user_id=uuid4(), role="user")
    header = pyjwt.get_unverified_header(token)
    assert header["kid"] == "k1"
    claims = await signer.verify_access(token)
    assert claims["sub"]


async def test_token_signed_with_old_kid_still_verifies(two_keys, fake_redis, monkeypatch):
    """After rotation to k2, tokens signed with k1 must still verify (until expiry).

    This is the core zero-downtime guarantee: rotate active kid → wait for old
    tokens to expire (15 min TTL) → then revoke old kid.
    """
    from app.core import redis as redis_mod

    monkeypatch.setattr(redis_mod, "get_redis", lambda: fake_redis)
    from app.identity.infrastructure.jwt_signer import JwtSigner

    # Sign with k1
    signer_k1 = JwtSigner()
    token = signer_k1.sign_access(user_id=uuid4(), role="user")

    # Simulate rotation: switch active kid to k2
    monkeypatch.setenv("JWT_ACTIVE_KID", "k2")
    from app.core.config import get_settings

    get_settings.cache_clear()
    signer_k2 = JwtSigner()

    # k1 token must still verify with signer_k2 (k1 pubkey still in registry)
    claims = await signer_k2.verify_access(token)
    assert claims["sub"]


async def test_revoked_kid_rejects_token(two_keys, fake_redis, monkeypatch):
    """Marking a kid as REVOKED must immediately block all tokens bearing that kid."""
    from app.core import redis as redis_mod

    monkeypatch.setattr(redis_mod, "get_redis", lambda: fake_redis)
    from app.identity.infrastructure.jwt_signer import JwtSigner

    signer = JwtSigner()
    token = signer.sign_access(user_id=uuid4(), role="user")  # k1

    # Revoke k1 and switch active to k2
    monkeypatch.setenv("JWT_REVOKED_KIDS", "k1")
    monkeypatch.setenv("JWT_ACTIVE_KID", "k2")
    from app.core.config import get_settings

    get_settings.cache_clear()
    signer2 = JwtSigner()

    with pytest.raises(Unauthenticated, match="kid_revoked"):
        await signer2.verify_access(token)


async def test_unknown_kid_rejected(two_keys, fake_redis, monkeypatch):
    """Forged token carrying an unknown kid must be rejected (anti-forgery guard)."""
    from app.core import redis as redis_mod

    monkeypatch.setattr(redis_mod, "get_redis", lambda: fake_redis)

    import jwt as pyjwt
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    # Attacker generates their own key and stamps a fake kid
    rogue = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    rogue_pem = rogue.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    token = pyjwt.encode(
        {
            "sub": "attacker",
            "aud": "nova-mobile",
            "iss": "nova-nutrition",
            "exp": 9_999_999_999,
            "iat": 1,
            "jti": "forged",
        },
        rogue_pem,
        algorithm="RS256",
        headers={"kid": "rogue"},
    )

    from app.identity.infrastructure.jwt_signer import JwtSigner

    signer = JwtSigner()

    with pytest.raises(Unauthenticated, match="kid_unknown"):
        await signer.verify_access(token)
