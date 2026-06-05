"""Phase 3 / T3.4 — ES↔EN parity for coach template messages.

Enforces the contract documented in
``docs/handoff/2026-06-05-i18n-runtime-locale-propagation-plan.md`` §Phase 3:

* every key in ``MESSAGES_ES`` MUST exist in ``MESSAGES_EN`` and vice-versa,
* every key MUST be reachable from at least one supported locale in the
  registry,
* registry keys MUST equal :data:`SUPPORTED_LOCALES`.

Also covers ``chat_message.py`` refuse templates by name parity (manual list
— they live as module constants, not dicts).
"""

from __future__ import annotations

from app.coach.application import chat_message as cm
from app.coach.application.template_responses import (
    MESSAGES_EN,
    MESSAGES_ES,
    MESSAGES_REGISTRY,
)
from app.shared.i18n import SUPPORTED_LOCALES


def test_messages_es_en_key_parity() -> None:
    es_keys = set(MESSAGES_ES.keys())
    en_keys = set(MESSAGES_EN.keys())
    assert es_keys == en_keys, (
        f"ES↔EN parity broken. ES-only={es_keys - en_keys}, EN-only={en_keys - es_keys}"
    )


def test_registry_covers_supported_locales() -> None:
    assert set(MESSAGES_REGISTRY.keys()) == set(SUPPORTED_LOCALES), (
        f"MESSAGES_REGISTRY keys {set(MESSAGES_REGISTRY.keys())} "
        f"!= SUPPORTED_LOCALES {set(SUPPORTED_LOCALES)}"
    )


def test_no_message_value_is_empty() -> None:
    for locale, catalogue in MESSAGES_REGISTRY.items():
        for key, value in catalogue.items():
            assert value.strip(), f"Empty/blank message {locale}/{key!r}"


def test_refuse_templates_parity() -> None:
    """``chat_message.py`` keeps refuse templates as module constants. Each
    ES constant MUST have an EN sibling."""
    pairs = [
        ("MEDICAL_TEMPLATE_ES", "MEDICAL_TEMPLATE_EN"),
        ("OFFTOPIC_TEMPLATE_ES", "OFFTOPIC_TEMPLATE_EN"),
        ("INJECTION_TEMPLATE_ES", "INJECTION_TEMPLATE_EN"),
    ]
    for es_name, en_name in pairs:
        es_val = getattr(cm, es_name, None)
        en_val = getattr(cm, en_name, None)
        assert isinstance(es_val, str) and es_val.strip(), f"{es_name} missing/empty"
        assert isinstance(en_val, str) and en_val.strip(), f"{en_name} missing/empty"


def test_system_prompt_language_suffix_for_each_locale() -> None:
    """``system_prompt_for`` must append a non-empty language instruction."""
    base = cm.SYSTEM_PROMPT
    for locale in SUPPORTED_LOCALES:
        rendered = cm.system_prompt_for(locale)
        assert rendered.startswith(base), f"{locale}: suffix did not append"
        suffix = rendered[len(base) :]
        assert suffix.strip(), f"{locale}: empty suffix"


def test_coach_tone_no_forbidden_words_in_messages() -> None:
    """COACH_TONE.md §Forbidden vocabulary — none must appear in any locale.

    Conservative ES list; EN list mirrors the spirit (no ``failed``,
    ``wrong``, ``must``, ``ruined``, ``disappointing``).
    """
    forbidden_es = (
        "fallaste",
        "fracasaste",
        "te equivocaste",
        "te excediste",
        "abusaste",
        "arruinaste",
        "decepcionante",
        "preocupante",
        "no cumpliste",
        "no lograste",
    )
    forbidden_en = (
        "you failed",
        "you screwed",
        "you must",
        "you have to",
        "ruined",
        "disappointing",
    )
    for key, value in MESSAGES_ES.items():
        lower = value.lower()
        for bad in forbidden_es:
            assert bad not in lower, f"ES {key!r} contains forbidden {bad!r}"
    for key, value in MESSAGES_EN.items():
        lower = value.lower()
        for bad in forbidden_en:
            assert bad not in lower, f"EN {key!r} contains forbidden {bad!r}"
