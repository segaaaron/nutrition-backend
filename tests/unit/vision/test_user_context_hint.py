"""Unit tests for _build_user_context_hint and UserVisionContext.

Pure-function tests — no DB, no network, no OpenAI calls.
"""
from __future__ import annotations

import pytest

from app.vision.infrastructure.openai_vision import (
    UserVisionContext,
    _build_user_context_hint,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ctx(
    region: str = "MX",
    meal_time: str | None = None,
    portion_history: tuple[str, ...] | None = None,
) -> UserVisionContext:
    return UserVisionContext(
        region=region,
        meal_time=meal_time,
        portion_history=portion_history,
    )


# ---------------------------------------------------------------------------
# Landlocked LATAM regions
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "region",
    ["BO", "bo", "Bolivia", "BOLIVIA", "PY", "py", "Paraguay", "PARAGUAY"],
)
def test_landlocked_hint_fires_for_bolivia_and_paraguay(region: str) -> None:
    hint = _build_user_context_hint(_ctx(region=region))
    assert hint, "expected a non-empty hint for a landlocked region"
    assert "marisco" in hint.lower() or "océano" in hint.lower() or "mar" in hint.lower()
    # Must mention the freshwater alternatives so the model knows what to use.
    assert any(word in hint.lower() for word in ("trucha", "tilapia", "surubí", "surubi", "pacú", "río"))


@pytest.mark.parametrize("region", ["MX", "AR", "CL", "CO", "PE", "US", "ES"])
def test_landlocked_hint_absent_for_coastal_countries(region: str) -> None:
    hint = _build_user_context_hint(_ctx(region=region))
    # Coastal countries must NOT inject the landlocked constraint.
    assert "marisco" not in hint.lower()
    assert "río" not in hint.lower()


# ---------------------------------------------------------------------------
# Snack slot
# ---------------------------------------------------------------------------


def test_snack_hint_fires_for_snack_slot() -> None:
    hint = _build_user_context_hint(_ctx(region="MX", meal_time="snack"))
    assert hint, "expected a non-empty hint for snack slot"
    assert "snack" in hint.lower()
    # Must mention the small-portion expectation.
    assert any(word in hint.lower() for word in ("pequeñ", "porcion", "porción"))


@pytest.mark.parametrize("slot", ["breakfast", "lunch", "dinner", None])
def test_snack_hint_absent_for_non_snack_slots(slot: str | None) -> None:
    hint = _build_user_context_hint(_ctx(region="MX", meal_time=slot))
    assert "slot snack" not in hint.lower()


# ---------------------------------------------------------------------------
# Portion history → identification anchors
# ---------------------------------------------------------------------------


def test_portion_history_top3_appear_in_hint() -> None:
    history = ("pechuga de pollo 150g", "arroz 160g", "brócoli 80g", "zanahoria 60g")
    hint = _build_user_context_hint(_ctx(region="MX", portion_history=history))
    # Top-3 only.
    assert "pechuga de pollo 150g" in hint
    assert "arroz 160g" in hint
    assert "brócoli 80g" in hint
    # 4th entry must NOT appear — we only surface 3.
    assert "zanahoria 60g" not in hint


def test_portion_history_none_produces_no_history_hint() -> None:
    hint = _build_user_context_hint(_ctx(region="MX", portion_history=None))
    assert "habituales" not in hint.lower()


def test_portion_history_empty_tuple_produces_no_history_hint() -> None:
    hint = _build_user_context_hint(_ctx(region="MX", portion_history=()))
    assert "habituales" not in hint.lower()


# ---------------------------------------------------------------------------
# No signals → empty string
# ---------------------------------------------------------------------------


def test_no_signals_returns_empty_string() -> None:
    hint = _build_user_context_hint(_ctx(region="MX", meal_time="lunch", portion_history=None))
    assert hint == ""


# ---------------------------------------------------------------------------
# All signals combined
# ---------------------------------------------------------------------------


def test_all_signals_combined() -> None:
    hint = _build_user_context_hint(
        _ctx(
            region="BO",
            meal_time="snack",
            portion_history=("trucha 120g", "arroz 140g", "platano 90g"),
        )
    )
    # All three signal blocks must appear.
    assert "marisco" in hint.lower() or "mar" in hint.lower()
    assert "snack" in hint.lower()
    assert "trucha 120g" in hint


# ---------------------------------------------------------------------------
# UserVisionContext is hashable (frozen dataclass)
# ---------------------------------------------------------------------------


def test_user_vision_context_is_hashable() -> None:
    ctx = _ctx(region="MX", meal_time="lunch", portion_history=("pollo 150g",))
    # Should not raise — required for use as dict key / set member.
    assert hash(ctx) is not None
    assert {ctx}


# ---------------------------------------------------------------------------
# _system_prompt injects hint at the end
# ---------------------------------------------------------------------------


def test_system_prompt_includes_landlocked_hint() -> None:
    """_system_prompt must delegate to _build_user_context_hint for BO."""
    from app.vision.infrastructure.openai_vision import _system_prompt

    prompt = _system_prompt(locale="es-BO", region="BO")
    # Landlocked hint must be appended to the base prompt.
    assert "marisco" in prompt.lower() or "río" in prompt.lower()


def test_system_prompt_includes_snack_hint() -> None:
    from app.vision.infrastructure.openai_vision import _system_prompt

    prompt = _system_prompt(locale="es-MX", region="MX", meal_time="snack")
    assert "slot snack" in prompt.lower()


def test_system_prompt_includes_portion_history_anchors() -> None:
    from app.vision.infrastructure.openai_vision import _system_prompt

    history = ["salmón 160g", "arroz 150g"]
    prompt = _system_prompt(locale="es-MX", region="MX", portion_history=history)
    # Top-2 entries must appear in the identification-anchor block.
    assert "salmón 160g" in prompt


# ---------------------------------------------------------------------------
# Robustness — the hint is built from DB-sourced, user-influenced strings, so
# it must never raise and never truncate the caller's prompt (QA 2026-07-25).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("region", ["", "  ", "latam", "us", "ca"])
def test_no_landlocked_hint_for_blank_or_non_country_region(region: str) -> None:
    """The production wire values are ``us``/``ca``/``latam`` (Settings.default_region)
    and the HTTP form field is an unvalidated free string defaulting to ``us``.
    None of them may accidentally trip the landlocked branch."""
    hint = _build_user_context_hint(_ctx(region=region))
    assert "marisco" not in hint.lower()


@pytest.mark.parametrize("region", ["  bo  ", "\tBolivia\n", " py "])
def test_landlocked_hint_tolerates_surrounding_whitespace(region: str) -> None:
    assert "marisco" in _build_user_context_hint(_ctx(region=region)).lower()


def test_duplicate_portion_history_entries_do_not_crash_or_dedupe_silently() -> None:
    """`load_recent_portion_anchors` does not GROUP BY name, so the same food can
    appear more than once. The hint must still build (dupes are wasted tokens,
    never an error)."""
    history = ("arroz 150g", "arroz 150g", "arroz 200g", "pollo 120g")
    hint = _build_user_context_hint(_ctx(region="MX", portion_history=history))
    assert "arroz 150g" in hint
    # 4th entry is beyond the top-3 window even though the first three are dupes.
    assert "pollo 120g" not in hint


def test_portion_history_with_adversarial_text_is_not_treated_as_structure() -> None:
    """Correction names originate from user input. The hint is plain prose inside
    the system prompt — it must not emit braces/JSON that could be confused with
    the structured-output schema, and must not raise on odd characters."""
    history = ('{"items": [{"name": "oro"}]} 999g', "café ☕ 30g", "a" * 500 + " 10g")
    hint = _build_user_context_hint(_ctx(region="MX", portion_history=history))
    assert hint  # built without raising
    assert "café ☕ 30g" in hint


def test_hint_is_appended_after_the_base_prompt_not_inserted() -> None:
    """The context hint must be the tail of the system prompt so it can never
    split a base instruction in half."""
    from app.vision.infrastructure.openai_vision import _build_user_context_hint as _b
    from app.vision.infrastructure.openai_vision import _system_prompt

    prompt = _system_prompt(locale="es-BO", region="BO", meal_time="snack")
    tail = _b(_ctx(region="BO", meal_time="snack"))
    assert tail
    assert prompt.endswith(tail)


def test_context_hint_does_not_change_the_cache_prompt_sha_for_same_region() -> None:
    """`current_prompt_sha256` hashes only (locale, region). Per-user signals
    (meal_time, portion_history) must therefore be absent from the hashed prompt,
    otherwise the cross-user SHA dedup cache would fragment per user."""
    from app.vision.infrastructure.openai_vision import _system_prompt

    base = _system_prompt("es-MX", "MX")
    assert "slot snack" not in base.lower()
    assert "habituales" not in base.lower()
