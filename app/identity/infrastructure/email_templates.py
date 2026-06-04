"""Inline OTP email templates (HTML + text) — i18n-aware.

Design constraints (deliverability + privacy):
- No external images, no tracking pixels, no remote CSS
- Inline styles only; table layout for Outlook compatibility
- Plain-text fallback always included (Resend requires both for best
  spam-score)
- Variables: ``code`` (6-digit string), ``ttl_minutes`` (default 10)
- Supported locales: es (default), pt, en — others fall through to es
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Locale = Literal["es", "pt", "en"]

_DEFAULT_LOCALE: Locale = "es"

# (subject, intro, code_label, ttl_template, footer)
_STRINGS: dict[Locale, dict[str, str]] = {
    "es": {
        "subject": "Tu codigo de verificacion NOVA",
        "intro": "Hola,",
        "body": "Usa el siguiente codigo para completar tu verificacion en NOVA Nutrition:",
        "ttl": "Este codigo expira en {ttl_minutes} minutos.",
        "ignore": "Si no solicitaste este codigo, ignora este correo.",
        "footer": "NOVA Nutrition",
    },
    "pt": {
        "subject": "Seu codigo de verificacao NOVA",
        "intro": "Ola,",
        "body": "Use o codigo abaixo para concluir sua verificacao no NOVA Nutrition:",
        "ttl": "Este codigo expira em {ttl_minutes} minutos.",
        "ignore": "Se voce nao solicitou este codigo, ignore este e-mail.",
        "footer": "NOVA Nutrition",
    },
    "en": {
        "subject": "Your NOVA verification code",
        "intro": "Hello,",
        "body": "Use the code below to complete your verification on NOVA Nutrition:",
        "ttl": "This code expires in {ttl_minutes} minutes.",
        "ignore": "If you did not request this code, please ignore this email.",
        "footer": "NOVA Nutrition",
    },
}


@dataclass(slots=True, frozen=True)
class RenderedEmail:
    subject: str
    html: str
    text: str


def render_otp_email(
    *,
    code: str,
    ttl_minutes: int = 10,
    locale: str | None = None,
) -> RenderedEmail:
    """Render the OTP email in the requested locale (defaults to es)."""
    loc: Locale = (
        locale if locale in _STRINGS else _DEFAULT_LOCALE  # type: ignore[assignment]
    )
    s = _STRINGS[loc]
    ttl_line = s["ttl"].format(ttl_minutes=ttl_minutes)
    subject = s["subject"]

    html = (
        '<!DOCTYPE html><html><body style="margin:0;padding:0;'
        'font-family:Arial,sans-serif;background:#f5f5f5;">'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        'style="background:#f5f5f5;padding:24px;">'
        '<tr><td align="center">'
        '<table role="presentation" width="480" cellpadding="0" cellspacing="0" '
        'style="background:#ffffff;border-radius:8px;padding:32px;">'
        f'<tr><td style="font-size:16px;color:#222;">{s["intro"]}</td></tr>'
        f'<tr><td style="font-size:14px;color:#444;padding-top:12px;">{s["body"]}</td></tr>'
        '<tr><td align="center" style="padding:24px 0;">'
        f'<div style="font-size:32px;letter-spacing:8px;font-weight:bold;'
        f'color:#111;background:#f0f0f0;padding:16px 24px;border-radius:6px;'
        f'display:inline-block;">{code}</div>'
        '</td></tr>'
        f'<tr><td style="font-size:13px;color:#666;">{ttl_line}</td></tr>'
        f'<tr><td style="font-size:12px;color:#888;padding-top:16px;">{s["ignore"]}</td></tr>'
        '<tr><td style="font-size:12px;color:#aaa;padding-top:24px;'
        f'border-top:1px solid #eee;margin-top:16px;">{s["footer"]}</td></tr>'
        '</table></td></tr></table></body></html>'
    )

    text = (
        f"{s['intro']}\n\n"
        f"{s['body']}\n\n"
        f"    {code}\n\n"
        f"{ttl_line}\n\n"
        f"{s['ignore']}\n\n"
        f"-- {s['footer']}"
    )

    return RenderedEmail(subject=subject, html=html, text=text)
