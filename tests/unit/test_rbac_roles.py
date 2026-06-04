"""RBAC role hierarchy tests (OWASP API5, ASVS V4)."""

from __future__ import annotations

import pytest

from app.identity.domain.roles import VALID_ROLE_STRINGS, Role, role_at_least


def test_role_order_strict_total():
    assert Role.USER < Role.PREMIUM < Role.SUPPORT < Role.ADMIN


def test_from_str_canonical():
    assert Role.from_str("user") == Role.USER
    assert Role.from_str("premium") == Role.PREMIUM
    assert Role.from_str("support") == Role.SUPPORT
    assert Role.from_str("admin") == Role.ADMIN


def test_from_str_case_insensitive():
    assert Role.from_str("USER") == Role.USER
    assert Role.from_str("Admin") == Role.ADMIN


def test_from_str_unknown_raises():
    with pytest.raises(ValueError, match="unknown role"):
        Role.from_str("superuser")


def test_to_str_roundtrip():
    for s in VALID_ROLE_STRINGS:
        assert Role.from_str(s).to_str() == s


@pytest.mark.parametrize(
    "claim,required,expected",
    [
        ("admin", Role.USER, True),
        ("admin", Role.ADMIN, True),
        ("support", Role.SUPPORT, True),
        ("support", Role.ADMIN, False),
        ("premium", Role.USER, True),
        ("premium", Role.SUPPORT, False),
        ("user", Role.USER, True),
        ("user", Role.PREMIUM, False),
        ("user", Role.ADMIN, False),
        ("", Role.USER, False),
        ("invalid", Role.USER, False),
    ],
)
def test_role_at_least(claim, required, expected):
    assert role_at_least(claim, required) is expected


def test_valid_role_strings_complete():
    assert VALID_ROLE_STRINGS == {"user", "premium", "support", "admin"}
