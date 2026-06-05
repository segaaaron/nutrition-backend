"""Phase 3 / T3.4 — each template message renders without ``KeyError`` in
both supported locales when given its expected substitution kwargs.

We exercise the pure ``_render`` helper rather than the async DB handlers
(DB-free, fast). Handler-level integration is covered separately."""

from __future__ import annotations

import pytest

from app.coach.application.template_responses import MESSAGES_REGISTRY, _render
from app.shared.i18n import SUPPORTED_LOCALES, Locale

# Maps each known key to the substitution kwargs it expects. Keys without
# placeholders pass empty dict. Keys absent from this map are asserted to
# render with no kwargs (catches accidental placeholder additions).
_KWARGS_BY_KEY: dict[str, dict[str, object]] = {
    "today_plan_header": {},
    "today_plan_line": {"meal_time": "lunch", "name": "Arroz", "kcal": 500},
    "next_meal": {"meal_time": "lunch", "name": "Arroz", "kcal": 500},
    "streak_empty": {},
    "streak_header": {},
    "streak_line": {"kind": "logging", "value": 7},
    "water_goal_hit": {"total": 2000, "goal": 2000, "pct": 100},
    "water_in_progress": {"total": 1000, "goal": 2000, "pct": 50, "remaining": 1000},
    "water_no_goal": {"total": 500},
    "protein_remaining": {"remaining": 30, "consumed": 70, "goal": 100},
    "water_logged": {},
    "meal_name_unknown": {},
}


@pytest.mark.parametrize("locale", list(SUPPORTED_LOCALES))
def test_every_key_renders_in_every_locale(locale: Locale) -> None:
    catalogue = MESSAGES_REGISTRY[locale]
    for key in catalogue:
        kwargs = _KWARGS_BY_KEY.get(key, {})
        out = _render(locale, key, **kwargs)
        assert isinstance(out, str)
        assert out, f"{locale}/{key} rendered empty"
        # No leftover braces — placeholders all substituted.
        assert "{" not in out, f"{locale}/{key} has unresolved placeholder: {out!r}"


def test_render_unsupported_locale_falls_back_to_es() -> None:
    # Smuggle an unsupported locale past the type checker — `_render` must
    # return the ES translation rather than raising.
    bad: Locale = "xx"  # type: ignore[assignment]
    out = _render(bad, "streak_empty")
    assert out == MESSAGES_REGISTRY["es"]["streak_empty"]
