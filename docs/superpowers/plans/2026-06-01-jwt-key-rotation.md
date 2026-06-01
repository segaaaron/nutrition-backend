# JWT Key Rotation (kid header) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `kid` header support to JWT signing/verification so multiple keypairs can coexist, enabling zero-downtime key rotation and immediate revocation of a compromised key.

**Architecture:** `JwtSigner` reads a `jwt_signing_keys` env var (comma-separated `kid:path` pairs) into an internal registry `_keys: dict[str, tuple[bytes, bytes]]`. `sign_access` stamps the active kid into the JOSE header. `verify_access` reads the unverified header, looks up the matching public key, rejects revoked or unknown kids before cryptographic verification. Legacy single-key path is preserved when `jwt_signing_keys` is empty.

**Tech Stack:** PyJWT ≥ 2.x (already installed), pydantic-settings (already installed), cryptography (already installed, used in tests), fakeredis (already in test suite).

---

### File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `app/core/config.py` | Modify | Add 3 new settings fields for multi-key config |
| `app/identity/infrastructure/jwt_signer.py` | Modify | Rewrite `JwtSigner.__init__`, `sign_access`, `verify_access` to support key registry |
| `tests/unit/test_jwt_key_rotation.py` | Create | 4 new tests covering kid header, rotation, revoked kid, unknown kid |

---

### Task 1: Add settings fields for multi-key JWT

**Files:**
- Modify: `app/core/config.py` (lines 40–45, after `jwt_audience`)

- [ ] **Step 1: Add 3 new fields to `Settings` in `app/core/config.py`**

Insert after `jwt_audience: str = "nova-mobile"` (line 45):

```python
    # --- JWT key rotation (ASVS V2 / S0-J) ---
    # Comma-separated entries: "kid:path_to_priv.pem,kid2:path_to_priv2.pem"
    # Public key assumed at path.replace('.pem', '.pub')
    # If empty, falls back to jwt_private_key_path + jwt_public_key_path (legacy).
    jwt_signing_keys: str = ""
    jwt_active_kid: str = "key_v1"
    # Comma-separated kids to reject immediately (compromised keys)
    jwt_revoked_kids: str = ""
```

- [ ] **Step 2: Verify no import needed** — all new fields are `str` with defaults, no additional imports required.

- [ ] **Step 3: Commit**

```bash
git add app/core/config.py
git commit -m "feat(config): add jwt_signing_keys, jwt_active_kid, jwt_revoked_kids settings"
```

---

### Task 2: Rewrite JwtSigner to support key registry

**Files:**
- Modify: `app/identity/infrastructure/jwt_signer.py`

- [ ] **Step 1: Replace the `JwtSigner` class body**

Replace the entire `JwtSigner` class (lines 49–99) with:

```python
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
```

- [ ] **Step 2: Verify existing tests still pass** (legacy single-key path uses `jwt_active_kid` default `"key_v1"` as the fallback kid — the existing `keypair` fixture sets `JWT_PRIVATE_KEY_PATH` / `JWT_PUBLIC_KEY_PATH` and does NOT set `JWT_SIGNING_KEYS`, so legacy path activates)

```bash
.venv/bin/pytest tests/unit/test_jwt_pyjwt_equivalence.py tests/unit/test_jwt_revocation.py -v
```

Expected: all 5 existing tests PASS.

- [ ] **Step 3: Commit**

```bash
git add app/identity/infrastructure/jwt_signer.py
git commit -m "feat(security): S0-J — JWT signer key registry with kid header"
```

---

### Task 3: Write and verify new key-rotation tests

**Files:**
- Create: `tests/unit/test_jwt_key_rotation.py`

- [ ] **Step 1: Create the test file**

```python
"""JWT key rotation — kid header tests.

ASVS V2 / S0-J: multiple keypairs, zero-downtime rotation, revoked-kid rejection,
unknown-kid anti-forgery.
"""
from __future__ import annotations

import pytest
from uuid import uuid4

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
```

- [ ] **Step 2: Run only the new tests to verify they pass**

```bash
.venv/bin/pytest tests/unit/test_jwt_key_rotation.py -v
```

Expected output:
```
tests/unit/test_jwt_key_rotation.py::test_token_carries_active_kid_header PASSED
tests/unit/test_jwt_key_rotation.py::test_token_signed_with_old_kid_still_verifies PASSED
tests/unit/test_jwt_key_rotation.py::test_revoked_kid_rejects_token PASSED
tests/unit/test_jwt_key_rotation.py::test_unknown_kid_rejected PASSED
4 passed
```

- [ ] **Step 3: Run the full JWT suite to confirm no regressions**

```bash
.venv/bin/pytest tests/unit/test_jwt_key_rotation.py tests/unit/test_jwt_pyjwt_equivalence.py tests/unit/test_jwt_revocation.py -v
```

Expected: all 9 tests PASS.

- [ ] **Step 4: Commit**

```bash
git add tests/unit/test_jwt_key_rotation.py
git commit -m "test(security): S0-J — JWT key rotation test suite (kid header, rotation, revocation)"
```

---

### Task 4: Final integration commit

- [ ] **Step 1: Squash/consolidate or create final commit**

If all three task commits are present and clean, create an annotated summary commit:

```bash
git add app/identity/infrastructure/jwt_signer.py app/core/config.py tests/unit/test_jwt_key_rotation.py
git commit -m "$(cat <<'EOF'
feat(security): S0-J — JWT key rotation via 'kid' header (ASVS V2)

JWT signer now supports N keypairs simultaneously. Active kid signs
new tokens; verify reads kid from header and selects matching pubkey.
Revoked kids reject immediately. Unknown kids reject (anti-forgery).

Backward compat: empty jwt_signing_keys falls back to single-key legacy.

Enables zero-downtime key rotation: deploy new kid, switch active,
wait for old tokens to expire (15min access TTL), revoke old kid.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Self-Review Checklist

- [x] `jwt_signing_keys`, `jwt_active_kid`, `jwt_revoked_kids` — all three settings added (Task 1)
- [x] `kid` in JOSE header on `sign_access` — Task 2
- [x] Multiple public keys supported — Task 2 key registry
- [x] Compromised key → mark REVOKED → immediate rejection — Task 2 + Task 3 test
- [x] Unknown kid → reject (anti-forgery) — Task 2 + Task 3 test
- [x] Backward compat (legacy single-key path) — Task 2, verified in Task 2 step 2
- [x] `test_token_carries_active_kid_header` — Task 3
- [x] `test_token_signed_with_old_kid_still_verifies` — Task 3 (zero-downtime guarantee)
- [x] `test_revoked_kid_rejects_token` — Task 3
- [x] `test_unknown_kid_rejected` — Task 3
- [x] All existing JWT tests unbroken — verified in Task 2 step 2 and Task 3 step 3
- [x] No placeholders — all code is complete and runnable
- [x] Type consistency — `_keys: dict[str, tuple[bytes, bytes]]` used consistently throughout
