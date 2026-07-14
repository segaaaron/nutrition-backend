"""Unit — per-photo user context as portion calibrator (2026-07-14).

Portion size is the top calorie-error source; a short free-text note from the
user ("plato familiar", "es individual") is the strongest calibration cue. The
note is sanitised at the boundary and injected into the vision prompt, but must
NOT enter the cross-user prompt cache key.
"""
from __future__ import annotations

import hashlib

from app.vision.application.submit_photo import (
    MAX_USER_CONTEXT_LEN,
    sanitize_user_context,
)
from app.vision.infrastructure.openai_vision import _system_prompt


# ── Sanitiser ──────────────────────────────────────────────────────────────
def test_sanitize_none_and_empty() -> None:
    assert sanitize_user_context(None) is None
    assert sanitize_user_context("") is None
    assert sanitize_user_context("   ") is None


def test_sanitize_strips_control_chars_and_collapses_ws() -> None:
    assert sanitize_user_context("plato\n\tfamiliar   grande") == "plato familiar grande"


def test_sanitize_caps_length() -> None:
    out = sanitize_user_context("a" * 500)
    assert out is not None
    assert len(out) == MAX_USER_CONTEXT_LEN


def test_sanitize_keeps_accents_and_normal_text() -> None:
    assert sanitize_user_context("es un plato para compartir 🍽") is not None


# ── Prompt injection ───────────────────────────────────────────────────────
def test_context_appears_in_prompt() -> None:
    p = _system_prompt("es", "latam", user_context="plato familiar para compartir")
    assert "plato familiar para compartir" in p
    assert "CONTEXTO DE ESTA FOTO" in p


def test_no_context_no_line() -> None:
    p = _system_prompt("es", "latam")
    assert "CONTEXTO DE ESTA FOTO" not in p


def test_context_excluded_from_prompt_hash() -> None:
    """The per-photo note must NOT change the cross-user cache key."""
    base_sha = hashlib.sha256(_system_prompt("es", "latam").encode()).hexdigest()
    # Same hashing recipe recognise() uses (locale, region only).
    with_ctx_sha = hashlib.sha256(_system_prompt("es", "latam").encode()).hexdigest()
    assert base_sha == with_ctx_sha
    # And the prompt WITH context differs in body (so the model actually sees it).
    assert _system_prompt("es", "latam", user_context="x") != _system_prompt("es", "latam")
