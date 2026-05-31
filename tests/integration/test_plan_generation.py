"""End-to-end Layer 1 → 4 happy path with mocked OpenAI.

Integration-tagged; skipped unless testcontainers spins up Postgres+Timescale.
We mock the Layer-4 client and exercise the pure orchestrator paths.
"""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest

pytestmark = pytest.mark.integration


class _StubLayer1:
    async def __call__(self, *, user_id, meal_time):
        return [uuid4() for _ in range(20)]


class _StubLayer2:
    async def __call__(
        self, *, candidate_ids, meal_time, kcal_target_share,
        protein_target_share, forbidden_ids, top_k=20,
    ):
        return [(cid, 1.0) for cid in candidate_ids[:top_k]]


class _StubLayer3:
    async def __call__(
        self, *, user_id, candidate_ids, meal_time,
        novelty_counts=None, adherence_rates=None,
    ):
        return [(cid, 0.5) for cid in candidate_ids]


class _StubLayer4Client:
    async def __call__(self, *, user_profile, candidate_plan, alternatives_by_slot):
        return {"ok": True, "swaps": [], "why_paragraph": ""}


@pytest.mark.skip(reason="needs testcontainers DB + repository write path")
async def test_create_plan_happy_path() -> None:
    # Placeholder for the live integration run. Stubs above show the
    # contract the real pipeline must honour.
    pass
