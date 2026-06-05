"""Snapshot-style tests for OTP email rendering.

Covers the (purpose × locale) matrix:

* ``register`` (signup) × {es, en}
* ``reset`` × {es, en}
* ``login`` reuses signup copy (YAGNI separate template)

Asserts on the *visible* substrings (subject + body anchors) rather than
brute byte-equality so cosmetic HTML tweaks don't churn the suite.
XSS guard is exercised explicitly with a code containing HTML metachars.
"""

from __future__ import annotations

import pytest

from app.identity.domain.entities import OtpPurpose
from app.identity.infrastructure.email_templates import (
    PURPOSE_TEMPLATE_KEY,
    render_otp_email,
)
from app.shared.i18n import SUPPORTED_LOCALES, Locale


def test_purpose_template_key_covers_all_otp_purposes() -> None:
    """Adding a new ``OtpPurpose`` member MUST also map it here."""
    from typing import get_args

    assert set(PURPOSE_TEMPLATE_KEY.keys()) == set(get_args(OtpPurpose))


@pytest.mark.parametrize("locale", sorted(SUPPORTED_LOCALES))
def test_signup_register_renders_purpose_specific_subject(locale: Locale) -> None:
    rendered = render_otp_email(
        code="123456", ttl_minutes=10, purpose="register", locale=locale
    )
    if locale == "es":
        assert rendered.subject == "Confirma tu cuenta NOVA"
        assert "confirmar tu cuenta" in rendered.text
    else:
        assert rendered.subject == "Confirm your NOVA account"
        assert "confirm your account" in rendered.text
    assert "123456" in rendered.text
    assert "123456" in rendered.html
    assert "10 minut" in rendered.text  # ttl interpolated


@pytest.mark.parametrize("locale", sorted(SUPPORTED_LOCALES))
def test_reset_renders_purpose_specific_subject(locale: Locale) -> None:
    rendered = render_otp_email(
        code="654321", ttl_minutes=15, purpose="reset", locale=locale
    )
    if locale == "es":
        assert rendered.subject == "Restablece tu contrasena NOVA"
        assert "restablecer tu contrasena" in rendered.text
    else:
        assert rendered.subject == "Reset your NOVA password"
        assert "reset your password" in rendered.text
    assert "654321" in rendered.html
    assert "15 minut" in rendered.text


@pytest.mark.parametrize("locale", sorted(SUPPORTED_LOCALES))
def test_login_purpose_reuses_signup_template(locale: Locale) -> None:
    signup = render_otp_email(code="000111", purpose="register", locale=locale)
    login = render_otp_email(code="000111", purpose="login", locale=locale)
    assert signup.subject == login.subject
    assert signup.html == login.html
    assert signup.text == login.text


def test_locale_none_defaults_to_es() -> None:
    rendered = render_otp_email(code="222333", purpose="register", locale=None)
    assert rendered.subject == "Confirma tu cuenta NOVA"


def test_html_escapes_code_metacharacters() -> None:
    """Defence-in-depth: if a malicious code ever reaches the renderer,
    it must not break out of the HTML context. Real OTPs are 6 digits but
    the renderer must not assume that."""
    rendered = render_otp_email(
        code="<script>alert(1)</script>", purpose="register", locale="en"
    )
    assert "<script>" not in rendered.html
    assert "&lt;script&gt;" in rendered.html
    # Plain text is not an HTML context — pass through is acceptable there.
    assert "<script>" in rendered.text


def test_subjects_differ_signup_vs_reset_per_locale() -> None:
    """Locked decision 3: different subjects per purpose, per locale."""
    for locale in ("es", "en"):
        signup = render_otp_email(code="1", purpose="register", locale=locale)  # type: ignore[arg-type]
        reset = render_otp_email(code="1", purpose="reset", locale=locale)  # type: ignore[arg-type]
        assert signup.subject != reset.subject


def test_pt_locale_is_not_in_mvp_matrix() -> None:
    """D2 lock: PT/FR/DE not shipped in MVP. ``Locale`` Literal excludes them."""
    assert "pt" not in SUPPORTED_LOCALES
    assert "fr" not in SUPPORTED_LOCALES
    assert "de" not in SUPPORTED_LOCALES
