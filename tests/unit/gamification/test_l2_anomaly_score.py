"""ADR-0026 L2 anomaly score — unit + property tests.

Strategy
--------
The signal modules are pure async functions over a SQL session. We unit
test the *pure-Python* helpers (entropy, hamming clustering, ratio→score,
correlation→score, weighted aggregation) directly, and integration-style
exercise the orchestrator (`anomaly_score_task.aggregate_score`,
`_apply_action`) with a stub session that records SQL writes.

Hypothesis property tests guarantee the documented invariants:

* every signal helper returns a value in ``[0, 100]``;
* aggregation is monotonic in each input signal;
* weight redistribution preserves the ``[0, 100]`` bound when arbitrary
  subsets of signals are unavailable.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from worker.anomaly_score_task import (
    BAN_THRESHOLD,
    REVIEW_THRESHOLD,
    SIGNAL_WEIGHTS,
    _apply_action,
    _hash_uid,
    aggregate_score,
)
from worker.anomaly_signals.log_timing import _entropy_score
from worker.anomaly_signals.macro_impossibility import _ratio_to_score
from worker.anomaly_signals.phash_clustering import _cluster_count, _hamming
from worker.anomaly_signals.weight_intake import (
    _correlation_to_score,
    _pearson,
)

pytestmark = pytest.mark.anyio


# ---------------------------------------------------------------------------
# log_timing._entropy_score
# ---------------------------------------------------------------------------


def test_entropy_score_single_bucket_is_max_suspicious():
    # All logs at hour=8 over 7 days → zero entropy → score 100.
    hours = [8] * 20
    score = _entropy_score(hours, window_days=7)
    assert score == pytest.approx(100.0)


def test_entropy_score_uniform_is_low():
    # 168 distinct (hour-of-day) buckets cannot all be hit by 24 hours,
    # but the *normalisation* uses 7*24=168 as the max so uniform-over-24
    # yields entropy log2(24) ≈ 4.585 → score = 100 - 4.585/7.392*100 ≈ 38.
    hours = list(range(24))
    score = _entropy_score(hours, window_days=7)
    assert 30.0 < score < 50.0


def test_entropy_score_bounds():
    assert _entropy_score([1, 2], window_days=7) >= 0.0
    assert _entropy_score([1] * 50, window_days=7) <= 100.0


@given(
    hours=st.lists(st.integers(min_value=0, max_value=23), min_size=2, max_size=200),
    days=st.integers(min_value=1, max_value=30),
)
@settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
def test_entropy_score_always_in_range(hours: list[int], days: int):
    s = _entropy_score(hours, window_days=days)
    assert 0.0 <= s <= 100.0


# ---------------------------------------------------------------------------
# phash_clustering._hamming + _cluster_count
# ---------------------------------------------------------------------------


def test_hamming_zero_for_equal():
    assert _hamming(0xDEADBEEF, 0xDEADBEEF) == 0


def test_hamming_counts_bits():
    assert _hamming(0b1010, 0b0101) == 4


def test_cluster_count_empty():
    assert _cluster_count([]) == 0
    assert _cluster_count([42]) == 0


def test_cluster_count_all_duplicates():
    hashes = [0xAAAA, 0xAAAA, 0xAAAA]
    # All hamming-0 → all matched → count == 3.
    assert _cluster_count(hashes) == 3


def test_cluster_count_no_neighbours():
    # Hashes differ in >=5 bits pairwise.
    hashes = [0x00, 0xFF, 0xFF00, 0xFF0000]
    assert _cluster_count(hashes) == 0


# ---------------------------------------------------------------------------
# macro_impossibility._ratio_to_score
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "ratio,expected",
    [
        (0.5, 0.0),  # below 1.0 clipped to 0
        (1.0, 0.0),
        (2.0, 50.0),
        (3.0, 100.0),
        (5.0, 100.0),  # clipped upper
    ],
)
def test_ratio_to_score(ratio: float, expected: float):
    assert _ratio_to_score(ratio) == pytest.approx(expected)


@given(ratio=st.floats(min_value=0.0, max_value=10.0, allow_nan=False))
def test_ratio_to_score_bounds(ratio: float):
    s = _ratio_to_score(ratio)
    assert 0.0 <= s <= 100.0


@given(
    r1=st.floats(min_value=1.0, max_value=4.0),
    r2=st.floats(min_value=1.0, max_value=4.0),
)
def test_ratio_to_score_monotonic(r1: float, r2: float):
    if r1 <= r2:
        assert _ratio_to_score(r1) <= _ratio_to_score(r2)


# ---------------------------------------------------------------------------
# weight_intake._pearson + _correlation_to_score
# ---------------------------------------------------------------------------


def test_pearson_perfect_positive():
    assert _pearson([1, 2, 3, 4], [2, 4, 6, 8]) == pytest.approx(1.0)


def test_pearson_perfect_negative():
    assert _pearson([1, 2, 3, 4], [4, 3, 2, 1]) == pytest.approx(-1.0)


def test_pearson_zero_variance_is_none():
    assert _pearson([1, 1, 1], [1, 2, 3]) is None


def test_pearson_too_short_is_none():
    assert _pearson([1], [2]) is None


def test_correlation_to_score():
    assert _correlation_to_score(1.0) == pytest.approx(0.0)
    assert _correlation_to_score(0.0) == pytest.approx(50.0)
    assert _correlation_to_score(-1.0) == pytest.approx(100.0)
    # Defensive clamp.
    assert _correlation_to_score(2.0) == pytest.approx(0.0)
    assert _correlation_to_score(-2.0) == pytest.approx(100.0)


@given(c=st.floats(min_value=-1.0, max_value=1.0, allow_nan=False))
def test_correlation_to_score_bounds(c: float):
    s = _correlation_to_score(c)
    assert 0.0 <= s <= 100.0


# ---------------------------------------------------------------------------
# aggregate_score (weight redistribution + bounds)
# ---------------------------------------------------------------------------


def _all_signals(value: float) -> dict[str, float | None]:
    return {name: value for name in SIGNAL_WEIGHTS}


def test_aggregate_all_zero_is_zero():
    score, available = aggregate_score(_all_signals(0.0))
    assert score == 0.0
    assert set(available) == set(SIGNAL_WEIGHTS)


def test_aggregate_all_max_is_100():
    score, available = aggregate_score(_all_signals(100.0))
    assert score == pytest.approx(100.0)
    assert set(available) == set(SIGNAL_WEIGHTS)


def test_aggregate_all_none_returns_zero_empty():
    score, available = aggregate_score({name: None for name in SIGNAL_WEIGHTS})
    assert score == 0.0
    assert available == []


def test_aggregate_redistributes_when_signals_missing():
    # Only macro_impossibility (weight 0.20) available at value 100 →
    # redistributed gives a final score of 100, not 20.
    signals: dict[str, float | None] = {name: None for name in SIGNAL_WEIGHTS}
    signals["macro_impossibility"] = 100.0
    score, available = aggregate_score(signals)
    assert score == pytest.approx(100.0)
    assert available == ["macro_impossibility"]


def test_aggregate_clips_out_of_range_inputs():
    signals: dict[str, float | None] = _all_signals(50.0)
    signals["macro_impossibility"] = 9999.0  # adversarial
    score, _ = aggregate_score(signals)
    assert 0.0 <= score <= 100.0


@given(
    values=st.dictionaries(
        keys=st.sampled_from(list(SIGNAL_WEIGHTS.keys())),
        values=st.one_of(
            st.none(),
            st.floats(min_value=0.0, max_value=100.0, allow_nan=False),
        ),
        min_size=0,
        max_size=len(SIGNAL_WEIGHTS),
    )
)
def test_aggregate_always_in_range(values: dict[str, float | None]):
    # Fill any missing keys with None so the orchestrator contract holds.
    full: dict[str, float | None] = {name: None for name in SIGNAL_WEIGHTS}
    full.update(values)
    score, _ = aggregate_score(full)
    assert 0.0 <= score <= 100.0


@given(
    base=st.floats(min_value=0.0, max_value=100.0, allow_nan=False),
    bump=st.floats(min_value=0.0, max_value=100.0, allow_nan=False),
    bumped_signal=st.sampled_from(list(SIGNAL_WEIGHTS.keys())),
)
def test_aggregate_monotonic_in_each_signal(
    base: float, bump: float, bumped_signal: str
):
    a = _all_signals(base)
    b = dict(a)
    b[bumped_signal] = max(0.0, min(100.0, base + bump))
    score_a, _ = aggregate_score(a)
    score_b, _ = aggregate_score(b)
    # Bumping any signal upward must not lower the aggregate score.
    assert score_b + 1e-9 >= score_a


# ---------------------------------------------------------------------------
# Threshold boundary determinism
# ---------------------------------------------------------------------------


class _FakeSession:
    """Records executed SQL so we can assert on shadow-ban INSERT."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def execute(self, stmt: Any, params: dict[str, Any] | None = None) -> Any:
        # stmt is a SQLAlchemy TextClause; .text holds the SQL string.
        sql = getattr(stmt, "text", str(stmt))
        self.calls.append((sql, params or {}))
        return None


async def test_action_ban_at_threshold():
    session = _FakeSession()
    uid = uuid4()
    signals: dict[str, float | None] = _all_signals(BAN_THRESHOLD)
    action = await _apply_action(
        session,  # type: ignore[arg-type]
        uid,
        BAN_THRESHOLD,
        signals,
        sorted(SIGNAL_WEIGHTS.keys()),
    )
    assert action == "banned"
    assert any("INSERT INTO gamification_shadow_ban" in sql for sql, _ in session.calls)
    inserted = [params for sql, params in session.calls if "INSERT" in sql][0]
    assert inserted["uid"] == str(uid)
    assert inserted["score"] == int(BAN_THRESHOLD)
    assert inserted["reason"] == f"anomaly_score>={int(BAN_THRESHOLD)}"


async def test_action_flag_at_review_threshold():
    session = _FakeSession()
    uid = uuid4()
    action = await _apply_action(
        session,  # type: ignore[arg-type]
        uid,
        REVIEW_THRESHOLD,
        _all_signals(REVIEW_THRESHOLD),
        sorted(SIGNAL_WEIGHTS.keys()),
    )
    assert action == "flagged"
    # Flag path must NOT write to DB.
    assert not any("INSERT" in sql for sql, _ in session.calls)


async def test_action_ok_below_review_threshold():
    session = _FakeSession()
    uid = uuid4()
    action = await _apply_action(
        session,  # type: ignore[arg-type]
        uid,
        REVIEW_THRESHOLD - 0.01,
        _all_signals(REVIEW_THRESHOLD - 0.01),
        sorted(SIGNAL_WEIGHTS.keys()),
    )
    assert action == "ok"
    assert not any("INSERT" in sql for sql, _ in session.calls)


async def test_action_no_data_when_all_signals_unavailable():
    session = _FakeSession()
    uid = uuid4()
    action = await _apply_action(
        session,  # type: ignore[arg-type]
        uid,
        0.0,
        {name: None for name in SIGNAL_WEIGHTS},
        [],
    )
    assert action == "no_data"
    assert not any("INSERT" in sql for sql, _ in session.calls)


# ---------------------------------------------------------------------------
# Privacy: user_id never logged
# ---------------------------------------------------------------------------


def test_hash_uid_deterministic_and_truncated():
    uid = UUID("12345678-1234-5678-1234-567812345678")
    h1 = _hash_uid(uid)
    h2 = _hash_uid(uid)
    assert h1 == h2
    assert len(h1) == 16
    # Raw uid never appears in the hash output.
    assert str(uid) not in h1
    assert "1234" not in h1 or h1 != str(uid)[:16]


def test_hash_uid_distinct_inputs_distinct_outputs():
    a = _hash_uid(uuid4())
    b = _hash_uid(uuid4())
    assert a != b


# ---------------------------------------------------------------------------
# Signal weights sanity
# ---------------------------------------------------------------------------


def test_signal_weights_sum_to_one():
    assert sum(SIGNAL_WEIGHTS.values()) == pytest.approx(1.0)
    assert all(0.0 < w < 1.0 for w in SIGNAL_WEIGHTS.values())
