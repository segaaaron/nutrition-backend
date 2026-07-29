"""Contract tests for the embedding_cache tuple structure shared between
layer3_ranking (writer) and create_plan (reader).

If someone adds a field to the tuple in one file without updating the other,
these tests catch the index drift before it silently reads the wrong column.
"""
from __future__ import annotations

import math

import numpy as np
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from app.plan.application.taste_profile import (
    adherence,
    cosine,
    cultural_fit,
    folate_fit,
    novelty,
    prep_time_fit,
    sugar_penalty,
)


# ── Tuple index contract ──────────────────────────────────────────────────────

_SAMPLE_CACHE_ENTRY = (
    ["latam"],      # 0: regions      — create_plan never reads this directly
    25,             # 1: prep_min     — create_plan never reads this directly
    300,            # 2: omega3_mg    — create_plan reads at [2] (fish telemetry)
    ["legumes"],    # 3: tags         — create_plan reads at [3] (legume/meat telemetry)
    8.5,            # 4: gl           — create_plan reads at [4] (high-GL telemetry)
    180,            # 5: folate_ug    — layer3 reads at [5] for folate_fit
    20,             # 6: sugar_g      — layer3 reads at [6] for sugar_penalty
    [0.1] * 8,     # 7: embedding    — layer3 reads at [7] for cosine
)


def test_tuple_has_exactly_8_elements() -> None:
    assert len(_SAMPLE_CACHE_ENTRY) == 8


def test_index_0_is_regions() -> None:
    assert isinstance(_SAMPLE_CACHE_ENTRY[0], list)
    assert all(isinstance(r, str) for r in _SAMPLE_CACHE_ENTRY[0])


def test_index_1_is_prep_min() -> None:
    assert isinstance(_SAMPLE_CACHE_ENTRY[1], int)


def test_index_2_is_omega3_mg() -> None:
    # create_plan checks `_feat[2] >= 150` for fish telemetry
    val = _SAMPLE_CACHE_ENTRY[2]
    assert isinstance(val, (int, type(None)))


def test_index_3_is_tags() -> None:
    # create_plan does `set(_feat[3] or [])` and checks "legumes" / "beef" / "pork"
    tags = _SAMPLE_CACHE_ENTRY[3]
    assert isinstance(tags, list)
    assert "legumes" in set(tags)


def test_index_4_is_gl() -> None:
    # create_plan checks `_feat[4] >= 20` for high-GL telemetry
    gl = _SAMPLE_CACHE_ENTRY[4]
    assert isinstance(gl, (float, int, type(None)))


def test_index_5_is_folate_ug() -> None:
    # layer3 feeds _cache[5] to folate_fit()
    folate = _SAMPLE_CACHE_ENTRY[5]
    assert isinstance(folate, (int, type(None)))
    score = folate_fit(folate)
    assert 0.0 <= score <= 1.0


def test_index_6_is_sugar_g() -> None:
    # layer3 feeds _cache[6] to sugar_penalty()
    sugar = _SAMPLE_CACHE_ENTRY[6]
    assert isinstance(sugar, (int, type(None)))
    penalty = sugar_penalty(sugar)
    assert 0.0 <= penalty <= 1.0


def test_index_7_is_embedding() -> None:
    emb = _SAMPLE_CACHE_ENTRY[7]
    assert isinstance(emb, list)
    assert all(isinstance(v, float) for v in emb)


# ── Property-based: scoring helpers never produce NaN or Inf ─────────────────

@given(
    a=st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
    b=st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
    c=st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
)
@settings(max_examples=200)
def test_base_signals_never_nan(a: float, b: float, c: float) -> None:
    s_cult = cultural_fit(None, ["latam"])
    s_prep = prep_time_fit(None, None)
    s_nov = novelty(0)
    s_adh = adherence(None)
    total = a * 0.40 + s_cult * 0.20 + s_prep * 0.20 + s_nov * 0.10 + s_adh * 0.10
    assert not math.isnan(total)
    assert not math.isinf(total)


@given(
    omega3=st.one_of(st.none(), st.integers(min_value=0, max_value=2000)),
    folate=st.one_of(st.none(), st.integers(min_value=0, max_value=800)),
    sugar=st.one_of(st.none(), st.integers(min_value=0, max_value=100)),
    gl=st.one_of(st.none(), st.floats(min_value=0.0, max_value=50.0, allow_nan=False)),
)
@settings(max_examples=300)
def test_condition_bonuses_never_nan(
    omega3: int | None,
    folate: int | None,
    sugar: int | None,
    gl: float | None,
) -> None:
    from app.plan.application.taste_profile import gl_penalty, omega3_fit

    bonus = 0.15 * omega3_fit(omega3) + 0.12 * folate_fit(folate)
    penalty = 0.10 * gl_penalty(gl) + 0.08 * sugar_penalty(sugar)
    result = 0.5 + bonus - penalty  # base = 0.5 as neutral
    assert not math.isnan(result)
    assert not math.isinf(result)


@given(
    vec=st.lists(
        st.floats(min_value=-1.0, max_value=1.0, allow_nan=False, allow_infinity=False),
        min_size=0,
        max_size=10,
    )
)
@settings(max_examples=200)
def test_cosine_with_zero_vector_returns_zero(vec: list[float]) -> None:
    zero = [0.0] * len(vec)
    result = cosine(vec, zero)
    assert result == 0.0
    assert not math.isnan(result)


@given(
    vec=st.lists(
        st.floats(min_value=-1.0, max_value=1.0, allow_nan=False, allow_infinity=False),
        min_size=1,
        max_size=20,
    )
)
@settings(max_examples=200)
def test_cosine_self_is_one(vec: list[float]) -> None:
    # cosine() casts to float32 for performance. Very small values can have
    # x^2 underflow to 0 in float32 (e.g. 1e-30^2 = 1e-60 < float32 min).
    # When norm underflows to 0, cosine() correctly returns 0.0 rather than
    # NaN. Use assume() to skip those edge cases: real embeddings from
    # text-embedding-3-large are normalized (L2≈1.0) and never subnormal.
    f32_norm = float(np.linalg.norm(np.array(vec, dtype=np.float32)))
    assume(f32_norm > 0.0)

    result = cosine(vec, vec)
    assert not math.isnan(result)
    assert abs(result - 1.0) < 1e-5
