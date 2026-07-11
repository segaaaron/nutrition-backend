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
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

import numpy as np
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
        weights = np.array(
            [DECAY_PER_WEEK ** max(0, weeks_ago) for weeks_ago, _ in history],
            dtype=np.float64,
        )
        total_w = weights.sum()
        if total_w == 0:
            return [0.0] * DIM
        matrix = np.array([emb for _, emb in history], dtype=np.float64)
        acc = (matrix * weights[:, np.newaxis]).sum(axis=0) / total_w
        return acc.tolist()


def cosine(a: list[float], b: list[float]) -> float:
    if not a or not b:
        return 0.0
    n = min(len(a), len(b))
    va = np.array(a[:n], dtype=np.float32)
    vb = np.array(b[:n], dtype=np.float32)
    na = float(np.linalg.norm(va))
    nb = float(np.linalg.norm(vb))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return float(np.dot(va, vb) / (na * nb))


# ISO-2 country → market region mapping. Used to score old-catalog recipes
# (tagged with market strings like "latam") when the user profile carries an
# ISO-2 country code. Keeps cultural_fit meaningful while both catalog
# generations coexist in prod.
_COUNTRY_TO_MARKET: dict[str, str] = {
    # LatAm
    "MX": "latam", "PE": "latam", "CO": "latam", "AR": "latam", "CL": "latam",
    "BO": "latam", "BR": "latam", "DO": "latam", "CU": "latam", "EC": "latam",
    "VE": "latam", "CR": "latam", "GT": "latam", "NI": "latam", "PA": "latam",
    "HN": "latam", "PY": "latam", "SV": "latam", "UY": "latam",
    # North America
    "US": "us", "CA": "ca",
    # Europe/UK removed 2026-07-10 — only US, Canada, LATAM are supported.
}


def cultural_fit(user_country: str | None, recipe_regions: list[str]) -> float:
    """Cultural relevance score bridging ISO-2 country codes and market tags.

    The catalog is in transition: old recipes use market strings (``latam``,
    ``us``, ``eu``) while v3 recipes use ISO-2 codes (``pe``, ``mx``, …).
    This function handles both so Layer 3 ranking stays meaningful during the
    migration instead of collapsing to 0.0 for all old-catalog recipes.

    Scoring:
        - 1.0  exact ISO-2 match          (v3 catalog, best signal)
        - 0.8  user's market matches tag  (old catalog, good signal)
        - 0.7  recipe tagged ``world``    (universal, neutral)
        - 0.0  foreign market/country     (hard cultural miss)
    """
    if not user_country or not recipe_regions:
        return 0.7  # no info → treat as world
    cc = user_country.upper().strip()
    normalised = [r.strip().upper() for r in recipe_regions]
    if cc in normalised:
        return 1.0
    user_market = _COUNTRY_TO_MARKET.get(cc, "").upper()
    if user_market and user_market in normalised:
        return 0.8
    if "WORLD" in normalised:
        return 0.7
    return 0.0


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


# Per-meal omega-3 (EPA+DHA) at which a recipe earns the full promotion bonus.
# ~250-500 mg/day EPA+DHA is the general adult target (DGA); oily-fish meals
# clear ~150 mg/portion, so 150 mg saturates the per-meal signal.
_OMEGA3_FULL_MG = 150


def omega3_fit(omega3_mg: int | None) -> float:
    """0..1 promotion signal for omega-3 content. NULL/unknown → 0 (no boost,
    never a penalty). Used only for conditions where oily fish is diet therapy
    (e.g. fatty_liver/NAFLD)."""
    if not omega3_mg or omega3_mg <= 0:
        return 0.0
    return min(1.0, omega3_mg / _OMEGA3_FULL_MG)
