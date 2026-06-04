"""Identity value-object property tests."""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.identity.domain.value_objects import Email, PasswordHash, Token


def test_email_normalises_lower():
    assert Email("Miguel@Example.COM").normalized == "miguel@example.com"


@pytest.mark.parametrize("bad", ["", "foo", "foo@bar", "@bar.com", "x@x", "x@x."])
def test_email_rejects_bad(bad: str):
    with pytest.raises(ValueError):
        Email(bad)


def test_password_hash_requires_argon2_prefix():
    with pytest.raises(ValueError):
        PasswordHash("plaintext")
    PasswordHash("$argon2id$v=19$m=65536,t=3,p=1$...$...")  # OK


@given(st.text(min_size=32, max_size=200))
def test_token_accepts_high_entropy(s: str):
    Token(s)  # no raise


@given(st.text(max_size=31))
def test_token_rejects_short(s: str):
    with pytest.raises(ValueError):
        Token(s)
