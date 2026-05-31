"""Recall@10 ≥ 0.85 sanity check against a synthetic golden query set.

Skipped unless `RUN_PERF=1` is set and a Postgres DSN with pgvector is
available — most CI runs don't have the data fixture loaded.
"""
from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_PERF") != "1",
    reason="perf suite requires RUN_PERF=1 + seeded pgvector dataset",
)


def test_recall_at_10_synthetic() -> None:
    # When enabled this test would:
    #   1. Load `tests/data/golden_queries.json` (query → expected recipe_ids)
    #   2. For each, run SqlRecipeRepository.semantic_search(top_k=10)
    #   3. Compute |returned ∩ expected| / |expected|
    #   4. Assert mean recall ≥ 0.85
    pytest.skip("placeholder — needs seeded dataset")
