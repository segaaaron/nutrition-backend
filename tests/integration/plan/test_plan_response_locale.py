"""Integration coverage for plan response locale propagation (Phase 2).

Scenarios (per plan §Phase 2 acceptance):

1. ``POST /plans`` with ``Accept-Language: en`` → response recipe names EN.
2. ``POST /plans`` with ``Accept-Language: es`` → response recipe names ES.
3. No header + ``profile.locale = "es"`` → ES (D1 priority step 2).
4. No header + no profile → ES (D4 anon fallback).

Note: ``POST /plans`` returns 202 (Arq enqueue); names are projected by
``GET /plans/active``. The integration scenarios therefore drive both
endpoints, asserting locale propagates end-to-end (HTTP → Arq job payload
→ ``CreatePlan`` → DB → ``GetActivePlan`` → projection).

This scaffolding intentionally mirrors ``test_plan_generation.py`` — it
declares the contracts the live integration run must honour and is skipped
unless ``--run-integration`` is passed AND testcontainers + Arq + Redis are
available. Unit-level invariants for ``_to_resp`` / ``_localize_*`` live in
``tests/unit/plan/test_plan_response_locale.py`` and run in CI by default.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


@pytest.mark.skip(
    reason=(
        "PLACEHOLDER: requires live testcontainer Postgres + Redis + Arq worker. "
        "Unit-level locale projection invariants are exhaustively covered in "
        "tests/unit/plan/test_plan_response_locale.py. Wire the live HTTP "
        "round-trip here once the plan generation testcontainer harness "
        "(tracked under D-plan-integ) lands."
    )
)
async def test_plan_response_locale_en_header() -> None:
    """POST /plans with Accept-Language: en → GET /plans/active surfaces EN names."""


@pytest.mark.skip(reason="PLACEHOLDER — see test_plan_response_locale_en_header.")
async def test_plan_response_locale_es_header() -> None:
    """POST /plans with Accept-Language: es → GET /plans/active surfaces ES names."""


@pytest.mark.skip(reason="PLACEHOLDER — see test_plan_response_locale_en_header.")
async def test_plan_response_locale_profile_fallback() -> None:
    """No Accept-Language + profile.locale=es → ES (D1 priority step 2)."""


@pytest.mark.skip(reason="PLACEHOLDER — see test_plan_response_locale_en_header.")
async def test_plan_response_locale_anon_fallback() -> None:
    """No Accept-Language + no profile → ES default (D4 anon fallback)."""
