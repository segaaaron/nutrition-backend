"""Inline OTP email templates (HTML + text) — i18n + purpose-aware.

Design constraints (deliverability + privacy + KISS):

* No external images, no tracking pixels, no remote CSS
* Inline styles only; table layout for Outlook compatibility
* Plain-text fallback always included (Resend recommends both)
* Variables: ``code`` (6-digit string), ``ttl_minutes`` (default 10)
* Supported locales (MVP, D2 lock): ``es``, ``en``. PT/FR/DE deferred.
* Supported purposes (mapped via :data:`PURPOSE_TEMPLATE_KEY`):
  ``register`` → signup copy, ``login`` → signup copy (YAGNI separate),
  ``reset`` → password-reset copy.

Architecture notes
------------------

The transport adapter (:class:`ResendEmailSender`) is intentionally
**locale-agnostic** — it only forwards an already-rendered ``subject``,
``html``, ``text`` payload. All localisation happens here so SRP is honored
(SOLID): renderer renders, transport transports. Adding a new locale = add
a dict row. Adding a new purpose = add a dict row + map it in
:data:`PURPOSE_TEMPLATE_KEY`.

XSS discipline: variables interpolated into HTML are escaped with
``html.escape`` (stdlib). Plain-text fallback skips escaping (no HTML
context). The static template strings contain no untrusted input.
"""

from __future__ import annotations

import html
from dataclasses import dataclass
from typing import Final, Literal

from app.identity.domain.entities import OtpPurpose
from app.shared.i18n.locale_resolver import Locale

_DEFAULT_LOCALE: Final[Locale] = "es"

# Internal template key. Decoupled from :data:`OtpPurpose` so the domain enum
# can grow without churning the template matrix (YAGNI: ``login`` reuses
# ``signup`` copy today; a dedicated ``login`` template can be added later by
# inserting a new key here and remapping in :data:`PURPOSE_TEMPLATE_KEY`).
_TemplateKey = Literal["signup", "reset"]

PURPOSE_TEMPLATE_KEY: Final[dict[OtpPurpose, _TemplateKey]] = {
    "register": "signup",
    "login": "signup",  # reuses signup copy (YAGNI separate template)
    "reset": "reset",
}

# Matrix shape: _STRINGS[template_key][locale][field].
# Fields: subject, intro, body, ttl, ignore, footer.
# ``ttl`` is a ``str.format`` template with a single ``{ttl_minutes}`` slot.
_STRINGS: Final[dict[_TemplateKey, dict[Locale, dict[str, str]]]] = {
    "signup": {
        "es": {
            "subject": "Confirma tu cuenta NOVA",
            "intro": "Hola,",
            "body": (
                "Usa el siguiente codigo para confirmar tu cuenta en "
                "NOVA Nutrition:"
            ),
            "ttl": "Este codigo expira en {ttl_minutes} minutos.",
            "ignore": (
                "Si no creaste una cuenta en NOVA, ignora este correo."
            ),
            "footer": "NOVA Nutrition",
        },
        "en": {
            "subject": "Confirm your NOVA account",
            "intro": "Hello,",
            "body": (
                "Use the code below to confirm your account on "
                "NOVA Nutrition:"
            ),
            "ttl": "This code expires in {ttl_minutes} minutes.",
            "ignore": (
                "If you did not create a NOVA account, please ignore this email."
            ),
            "footer": "NOVA Nutrition",
        },
    },
    "reset": {
        "es": {
            "subject": "Restablece tu contrasena NOVA",
            "intro": "Hola,",
            "body": (
                "Usa el siguiente codigo para restablecer tu contrasena en "
                "NOVA Nutrition:"
            ),
            "ttl": "Este codigo expira en {ttl_minutes} minutos.",
            "ignore": (
                "Si no solicitaste restablecer tu contrasena, ignora este correo."
            ),
            "footer": "NOVA Nutrition",
        },
        "en": {
            "subject": "Reset your NOVA password",
            "intro": "Hello,",
            "body": (
                "Use the code below to reset your password on "
                "NOVA Nutrition:"
            ),
            "ttl": "This code expires in {ttl_minutes} minutes.",
            "ignore": (
                "If you did not request a password reset, please ignore this email."
            ),
            "footer": "NOVA Nutrition",
        },
    },
}


@dataclass(slots=True, frozen=True)
class RenderedEmail:
    """Already-localised payload handed to the transport adapter.

    The adapter (Resend / null / fake) never sees ``locale`` or ``purpose``
    — it only transmits these three fields. Keeps SRP intact.
    """

    subject: str
    html: str
    text: str


def _resolve_template_key(purpose: OtpPurpose) -> _TemplateKey:
    """Map a domain :data:`OtpPurpose` to an internal template key.

    Unknown purposes (defensive — should be unreachable given the
    ``Literal`` type) fall back to ``"signup"``.
    """
    return PURPOSE_TEMPLATE_KEY.get(purpose, "signup")


def _resolve_locale(locale: Locale | None) -> Locale:
    """Defensive widening: caller may pass ``None`` (legacy paths)."""
    if locale is None:
        return _DEFAULT_LOCALE
    return locale


def render_otp_email(
    *,
    code: str,
    ttl_minutes: int = 10,
    purpose: OtpPurpose = "register",
    locale: Locale | None = None,
) -> RenderedEmail:
    """Render the OTP email in the requested locale + purpose.

    Args:
        code: 6-digit numeric OTP. Will be HTML-escaped before interpolation.
        ttl_minutes: minutes until expiry. Interpolated via ``str.format``.
        purpose: OTP domain purpose; maps to ``signup`` or ``reset`` template.
        locale: MVP locale (``"es"`` or ``"en"``). ``None`` → ``"es"`` (D4).

    Returns:
        :class:`RenderedEmail` with already-localised subject/html/text.
    """
    tpl_key = _resolve_template_key(purpose)
    loc = _resolve_locale(locale)
    s = _STRINGS[tpl_key][loc]

    # XSS guard: ``code`` is generated server-side (digits only) but defence
    # in depth — never interpolate raw user-influenced input into HTML.
    code_safe = html.escape(code, quote=True)
    ttl_line_text = s["ttl"].format(ttl_minutes=ttl_minutes)
    ttl_line_html = html.escape(ttl_line_text, quote=False)

    subject = s["subject"]

    html_body = (
        '<!DOCTYPE html><html><body style="margin:0;padding:0;'
        'font-family:Arial,sans-serif;background:#f5f5f5;">'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        'style="background:#f5f5f5;padding:24px;">'
        '<tr><td align="center">'
        '<table role="presentation" width="480" cellpadding="0" cellspacing="0" '
        'style="background:#ffffff;border-radius:8px;padding:32px;">'
        f'<tr><td style="font-size:16px;color:#222;">{html.escape(s["intro"])}</td></tr>'
        f'<tr><td style="font-size:14px;color:#444;padding-top:12px;">{html.escape(s["body"])}</td></tr>'
        '<tr><td align="center" style="padding:24px 0;">'
        f'<div style="font-size:32px;letter-spacing:8px;font-weight:bold;'
        f'color:#111;background:#f0f0f0;padding:16px 24px;border-radius:6px;'
        f'display:inline-block;">{code_safe}</div>'
        '</td></tr>'
        f'<tr><td style="font-size:13px;color:#666;">{ttl_line_html}</td></tr>'
        f'<tr><td style="font-size:12px;color:#888;padding-top:16px;">{html.escape(s["ignore"])}</td></tr>'
        '<tr><td style="font-size:12px;color:#aaa;padding-top:24px;'
        f'border-top:1px solid #eee;margin-top:16px;">{html.escape(s["footer"])}</td></tr>'
        '</table></td></tr></table></body></html>'
    )

    text_body = (
        f"{s['intro']}\n\n"
        f"{s['body']}\n\n"
        f"    {code}\n\n"
        f"{ttl_line_text}\n\n"
        f"{s['ignore']}\n\n"
        f"-- {s['footer']}"
    )

    return RenderedEmail(subject=subject, html=html_body, text=text_body)
