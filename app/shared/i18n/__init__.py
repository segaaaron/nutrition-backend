"""Shared i18n primitives: locale resolution + Translator + FastAPI dep.

Phase 1 foundation per docs/handoff/2026-06-05-i18n-runtime-locale-propagation-plan.md.

Public surface kept intentionally small (KISS, D9). Other bounded contexts
import from this package only — never from internal modules.

MVP locales: ``"es"`` + ``"en"`` (D2). PT/FR/DE are NOT shipped in MVP.
"""

from __future__ import annotations

# Import order matters: ``fastapi_dep`` transitively imports
# ``app.identity`` which itself re-imports ``Locale`` from this package. We
# must bind the locale_resolver symbols on the package first so the partial
# module exposes ``Locale`` to the identity layer before ``fastapi_dep``
# starts pulling it. Breaks the import cycle without touching identity.
# isort: off
from app.shared.i18n.locale_resolver import (
    SUPPORTED_LOCALES,
    Locale,
    parse_accept_language,
    resolve_email_locale,
    resolve_locale,
)
from app.shared.i18n.translator import Translator, TranslatorProtocol
from app.shared.i18n.fastapi_dep import LocaleDep, get_locale
# isort: on

__all__ = [
    "SUPPORTED_LOCALES",
    "Locale",
    "LocaleDep",
    "Translator",
    "TranslatorProtocol",
    "get_locale",
    "parse_accept_language",
    "resolve_email_locale",
    "resolve_locale",
]
