"""PyJWT signer round-trip + claims contract."""
from __future__ import annotations

import tempfile
from pathlib import Path
from uuid import uuid4

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa


@pytest.fixture
def keypair(monkeypatch, tmp_path):
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


def test_sign_and_verify_access(keypair):
    from app.identity.infrastructure.jwt_signer import JwtSigner
    signer = JwtSigner()
    uid = uuid4()
    token = signer.sign_access(user_id=uid, role="user")
    claims = signer.verify_access(token)
    assert claims["sub"] == str(uid)
    assert claims["role"] == "user"
    assert claims["iss"] == "nova-nutrition"
    assert claims["aud"] == "nova-mobile"


def test_verify_rejects_tampered(keypair):
    from app.identity.infrastructure.jwt_signer import JwtSigner
    from app.core.errors import Unauthenticated
    signer = JwtSigner()
    token = signer.sign_access(user_id=uuid4(), role="user")
    head, payload, sig = token.split(".")
    bad = f"{head}.{payload}.{sig[:-2]}AA"
    with pytest.raises(Unauthenticated):
        signer.verify_access(bad)


def test_verify_rejects_wrong_audience(keypair, monkeypatch):
    from app.identity.infrastructure.jwt_signer import JwtSigner
    from app.core.errors import Unauthenticated
    signer = JwtSigner()
    token = signer.sign_access(user_id=uuid4(), role="user")
    monkeypatch.setattr(signer, "_audience", "wrong-audience")
    with pytest.raises(Unauthenticated):
        signer.verify_access(token)
