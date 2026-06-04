"""User taste-profile vector.

A 1536-dim rolling EMA of completed-meal recipe embeddings with weekly decay
of 0.92. Cold start uses the centroid of recipes matching the user's
onboarding tag preferences (or a zero vector if none).

Cached in Redis under `taste:{user_id}` for 24h. The recalibration job
invalidates this key when a user logs a new completed meal (handled in the
plan event handlers; out of scope here).
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from redis.asyncio import Redis

DECAY_PER_WEEK = 0.92
DIM = 1536


class _EmbeddingFetcher(Protocol):
    async def get_user_completed_embeddings(
        self, user_id: UUID, weeks_back: int = 8
    ) -> list[tuple[int, list[float]]]:
        """Returns [(weeks_ago, embedding), ...]."""
        ...

    async def get_onboarding_centroid(self, user_id: UUID) -> list[float] | None: ...


@dataclass(slots=True)
class TasteProfileService:
    redis: Redis
    fetcher: _EmbeddingFetcher
    ttl_s: int = 24 * 3600

    async def get_or_build(self, user_id: UUID) -> list[float]:
        key = f"taste:{user_id}"
        cached = await self.redis.get(key)
        if cached:
            try:
                return list(json.loads(cached))
            except Exception:  # noqa: BLE001,S110 — cache miss falls through to rebuild
                pass
        vec = await self._build(user_id)
        await self.redis.set(key, json.dumps(vec), ex=self.ttl_s)
        return vec

    async def _build(self, user_id: UUID) -> list[float]:
        history = await self.fetcher.get_user_completed_embeddings(user_id)
        if not history:
            cold = await self.fetcher.get_onboarding_centroid(user_id)
            return cold or [0.0] * DIM
        # weighted EMA: more recent (smaller weeks_ago) gets larger weight.
        acc = [0.0] * DIM
        total_w = 0.0
        for weeks_ago, emb in history:
            w = DECAY_PER_WEEK ** max(0, weeks_ago)
            total_w += w
            for i, v in enumerate(emb):
                acc[i] += w * v
        if total_w == 0:
            return [0.0] * DIM
        return [v / total_w for v in acc]


def cosine(a: list[float], b: list[float]) -> float:
    if not a or not b:
        return 0.0
    n = min(len(a), len(b))
    dot = sum(a[i] * b[i] for i in range(n))
    na = math.sqrt(sum(x * x for x in a[:n]))
    nb = math.sqrt(sum(x * x for x in b[:n]))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def cultural_fit(user_country: str | None, recipe_regions: list[str]) -> float:
    """1.0 if country in regions, 0.5 if any region overlap, else 0.0.

    The "country in regions" check works because catalog regions are 5-char
    short codes (us/ca/eu/uk/latam) and `recipes.regions` denormalises the
    user's home region after onboarding (spec §6).
    """
    if not user_country:
        return 0.5
    if not recipe_regions:
        return 0.0
    cc = user_country.lower()
    if cc in recipe_regions:
        return 1.0
    return 0.5 if recipe_regions else 0.0


def prep_time_fit(user_pref_min: int | None, recipe_prep_min: int | None) -> float:
    """1.0 if within ±5 min; linear decay to 0 at ±30 min away."""
    if user_pref_min is None or recipe_prep_min is None:
        return 0.5
    delta = abs(recipe_prep_min - user_pref_min)
    if delta <= 5:
        return 1.0
    if delta >= 30:
        return 0.0
    return 1.0 - (delta - 5) / 25.0


def novelty(times_seen_last_30d: int) -> float:
    return max(0.0, 1.0 - times_seen_last_30d / 10.0)


def adherence(completion_rate: float | None) -> float:
    """Historical completion rate of similar recipes. Cold-start = 0.5."""
    if completion_rate is None:
        return 0.5
    return max(0.0, min(1.0, completion_rate))
