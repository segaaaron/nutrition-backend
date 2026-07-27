"""Unit tests for the two-pass RecognisePlate application service.

All tests use mocks — no DB, no network.
"""
from __future__ import annotations

import asyncio
from decimal import Decimal
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from app.vision.application.recognise_plate import (
    RecognisePlate,
    RecognitionContext,
    RecognitionOutcome,
)
from app.vision.domain.entities import DetectedFoodItem
from app.vision.domain.value_objects import FoodIdentification, PortionEstimate


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ident(name: str, *, idx_unused: int = 0, confidence: float = 0.9) -> FoodIdentification:
    """Build a minimal FoodIdentification for testing."""
    return FoodIdentification(
        name=name,
        confidence=confidence,
        group="protein",
        role="main",
        prep_method="grilled",
        count=1,
        portion_kind="a_granel",
    )


def _est(index: int, *, grams: float = 150.0, confidence: float = 0.8) -> PortionEstimate:
    """Build a minimal PortionEstimate for testing."""
    return PortionEstimate(
        index=index,
        estimated_amount_g=Decimal(str(grams)),
        kcal=200,
        protein_g=30,
        carbs_g=5,
        fat_g=7,
        confidence=confidence,
    )


def _make_ctx(**kwargs: object) -> RecognitionContext:
    defaults: dict[str, object] = dict(
        image_bytes=b"fake-image",
        mime="image/jpeg",
        user_id=uuid4(),
        locale="es",
        region="MX",
    )
    defaults.update(kwargs)
    return RecognitionContext(**defaults)  # type: ignore[arg-type]


class _MockIdentifier:
    def __init__(
        self,
        items: list[FoodIdentification],
        sha: str = "identify-sha",
    ) -> None:
        self._items = items
        self._sha = sha

    async def identify(self, **_kwargs: object) -> tuple[list[FoodIdentification], str]:
        return self._items, self._sha

    def identification_prompt_sha256(self, *, locale: str, region: str) -> str:
        return self._sha


class _MockEstimator:
    def __init__(
        self,
        estimates: list[PortionEstimate],
        sha: str = "estimate-sha",
        raise_exc: Exception | None = None,
    ) -> None:
        self._estimates = estimates
        self._sha = sha
        self._raise_exc = raise_exc

    async def estimate(self, **_kwargs: object) -> tuple[list[PortionEstimate], str]:
        if self._raise_exc is not None:
            raise self._raise_exc
        return self._estimates, self._sha

    def estimation_prompt_sha256(self, *, locale: str, region: str) -> str:
        return self._sha


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_merge_aligns_by_index() -> None:
    """Happy path: two identifications + two matching estimates → merged items."""
    ids = [_ident("chicken"), _ident("rice")]
    ests = [_est(0, grams=150.0), _est(1, grams=200.0)]

    service = RecognisePlate(
        identifier=_MockIdentifier(ids),
        estimator=_MockEstimator(ests),
    )
    outcome = await service(ctx=_make_ctx())

    assert not outcome.degraded
    assert len(outcome.items) == 2
    assert outcome.items[0].name == "chicken"
    assert outcome.items[0].estimated_amount_g == Decimal("150.0")
    assert outcome.items[1].name == "rice"
    assert outcome.items[1].estimated_amount_g == Decimal("200.0")


@pytest.mark.asyncio
async def test_merge_missing_index_degrades_item() -> None:
    """If estimator omits an index, that item is individually degraded (confidence=0.2)."""
    ids = [_ident("chicken"), _ident("rice")]
    # Only estimate for index 0; index 1 is missing
    ests = [_est(0, grams=150.0)]

    service = RecognisePlate(
        identifier=_MockIdentifier(ids),
        estimator=_MockEstimator(ests),
    )
    outcome = await service(ctx=_make_ctx())

    assert not outcome.degraded          # overall NOT degraded (Call 2 succeeded)
    assert len(outcome.items) == 2
    assert outcome.items[0].estimated_amount_g == Decimal("150.0")
    assert outcome.items[0].confidence > 0.2
    # Item at index 1 is individually degraded
    assert outcome.items[1].estimated_amount_g == Decimal("100")
    assert outcome.items[1].confidence == pytest.approx(0.2)


@pytest.mark.asyncio
async def test_degrade_sets_low_confidence() -> None:
    """_degrade() must set confidence ≤ 0.25 for every item."""
    ids = [_ident("x"), _ident("y"), _ident("z")]
    items = RecognisePlate._degrade(ids)

    assert len(items) == 3
    for it in items:
        assert it.confidence <= 0.25


@pytest.mark.asyncio
async def test_empty_identifications_returns_degraded() -> None:
    """If Call 1 returns empty list, outcome is degraded immediately."""
    service = RecognisePlate(
        identifier=_MockIdentifier([]),
        estimator=_MockEstimator([]),
    )
    outcome = await service(ctx=_make_ctx())

    assert outcome.degraded is True
    assert outcome.items == ()
    assert outcome.identification_conf_avg == 0.0
    assert outcome.estimation_conf_avg == 0.0


@pytest.mark.asyncio
async def test_hints_timeout_does_not_block() -> None:
    """Hint DB timeout must not prevent Call 2 from running."""
    ids = [_ident("chicken")]
    ests = [_est(0)]

    async def slow_hints(self_inner: object, _ids: object) -> dict:  # type: ignore[override]
        await asyncio.sleep(10)  # much longer than hints_timeout_s=0.01
        return {}  # pragma: no cover

    service = RecognisePlate(
        identifier=_MockIdentifier(ids),
        estimator=_MockEstimator(ests),
        hints_timeout_s=0.01,
    )

    with patch.object(RecognisePlate, "_load_hints", new=slow_hints):
        outcome = await service(ctx=_make_ctx())

    # Call 2 should have run successfully despite the hint timeout
    assert not outcome.degraded
    assert len(outcome.items) == 1
    assert outcome.items[0].name == "chicken"


@pytest.mark.asyncio
async def test_estimate_failure_degrades_gracefully() -> None:
    """If the estimator raises any exception, outcome is degraded but no crash."""
    ids = [_ident("chicken"), _ident("rice")]

    service = RecognisePlate(
        identifier=_MockIdentifier(ids),
        estimator=_MockEstimator([], raise_exc=RuntimeError("upstream down")),
    )
    outcome = await service(ctx=_make_ctx())

    assert outcome.degraded is True
    assert len(outcome.items) == 2
    # All items should have low confidence (degradation path)
    for it in outcome.items:
        assert it.confidence <= 0.25


@pytest.mark.asyncio
async def test_prompt_sha_composite(monkeypatch: pytest.MonkeyPatch) -> None:
    """prompt_sha256 must be identify_sha + ':' + estimate_sha (K=1, no composite hash)."""
    from app.core.config import get_settings
    get_settings.cache_clear()
    monkeypatch.setenv("VISION_SELF_CONSISTENCY_K", "1")
    get_settings.cache_clear()
    try:
        ids = [_ident("chicken")]
        ests = [_est(0)]

        service = RecognisePlate(
            identifier=_MockIdentifier(ids, sha="sha-id-abc"),
            estimator=_MockEstimator(ests, sha="sha-est-xyz"),
        )
        outcome = await service(ctx=_make_ctx())

        assert outcome.prompt_sha256 == "sha-id-abc:sha-est-xyz"
    finally:
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_prompt_sha_composite_on_degraded() -> None:
    """When estimator fails, sha is still identify_sha + ':' (empty estimate sha)."""
    ids = [_ident("chicken")]

    service = RecognisePlate(
        identifier=_MockIdentifier(ids, sha="sha-id-abc"),
        estimator=_MockEstimator([], raise_exc=ValueError("bad")),
    )
    outcome = await service(ctx=_make_ctx())

    assert outcome.degraded is True
    assert outcome.prompt_sha256 == "sha-id-abc:"


@pytest.mark.asyncio
async def test_confidence_is_minimum_of_both_axes() -> None:
    """Merged item confidence = min(id_conf, est_conf)."""
    ids = [_ident("chicken", confidence=0.9)]
    ests = [_est(0, confidence=0.6)]

    service = RecognisePlate(
        identifier=_MockIdentifier(ids),
        estimator=_MockEstimator(ests),
    )
    outcome = await service(ctx=_make_ctx())

    assert outcome.items[0].confidence == pytest.approx(0.6)


@pytest.mark.asyncio
async def test_identification_conf_avg_computed() -> None:
    """identification_conf_avg should be the arithmetic mean of all id confidences."""
    ids = [_ident("a", confidence=0.8), _ident("b", confidence=0.6)]
    ests = [_est(0), _est(1)]

    service = RecognisePlate(
        identifier=_MockIdentifier(ids),
        estimator=_MockEstimator(ests),
    )
    outcome = await service(ctx=_make_ctx())

    assert outcome.identification_conf_avg == pytest.approx(0.7)


# ---------------------------------------------------------------------------
# Self-consistency K tests
# ---------------------------------------------------------------------------


class _CountingEstimator:
    """Mock estimator that tracks call_count; every call returns the same result."""

    def __init__(
        self,
        estimates: list[PortionEstimate],
        sha: str = "sha-count",
    ) -> None:
        self._estimates = estimates
        self._sha = sha
        self.call_count = 0

    async def estimate(self, **_kwargs: object) -> tuple[list[PortionEstimate], str]:
        self.call_count += 1
        return self._estimates, self._sha

    def estimation_prompt_sha256(self, *, locale: str, region: str) -> str:
        return self._sha


class _MultiResponseEstimator:
    """Mock estimator that returns different results per call (iterator-based)."""

    def __init__(
        self,
        responses: list[tuple[list[PortionEstimate], str] | Exception],
    ) -> None:
        # Responses is consumed in order; each call pops the next entry.
        self._responses: list[tuple[list[PortionEstimate], str] | Exception] = list(responses)
        self._idx = 0

    async def estimate(self, **_kwargs: object) -> tuple[list[PortionEstimate], str]:
        entry = self._responses[self._idx % len(self._responses)]
        self._idx += 1
        if isinstance(entry, Exception):
            raise entry
        return entry

    def estimation_prompt_sha256(self, *, locale: str, region: str) -> str:
        return "multi-sha"


@pytest.mark.asyncio
async def test_consistency_k1_single_call(monkeypatch: pytest.MonkeyPatch) -> None:
    """k=1 → estimate() is called exactly once (self-consistency disabled)."""
    from app.core.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("VISION_SELF_CONSISTENCY_K", "1")

    ids = [_ident("chicken")]
    counting = _CountingEstimator([_est(0)])

    service = RecognisePlate(
        identifier=_MockIdentifier(ids),
        estimator=counting,
    )
    outcome = await service(ctx=_make_ctx())

    assert not outcome.degraded
    assert counting.call_count == 1
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_consistency_k3_median_aggregation(monkeypatch: pytest.MonkeyPatch) -> None:
    """k=3 → per-item median of estimated_amount_g across 3 concurrent calls.

    Run 0: 100 g, Run 1: 150 g, Run 2: 200 g → median = 150 g.
    """
    from app.core.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("VISION_SELF_CONSISTENCY_K", "3")

    ids = [_ident("chicken")]
    responses: list[tuple[list[PortionEstimate], str] | Exception] = [
        ([_est(0, grams=100.0, confidence=0.7)], "sha-r0"),
        ([_est(0, grams=150.0, confidence=0.8)], "sha-r1"),
        ([_est(0, grams=200.0, confidence=0.9)], "sha-r2"),
    ]
    multi = _MultiResponseEstimator(responses)

    service = RecognisePlate(
        identifier=_MockIdentifier(ids),
        estimator=multi,
    )
    outcome = await service(ctx=_make_ctx())

    assert not outcome.degraded
    assert len(outcome.items) == 1
    # Median of [100, 150, 200] = 150
    assert outcome.items[0].estimated_amount_g == pytest.approx(Decimal("150.0"))
    # Mean confidence = (0.7 + 0.8 + 0.9) / 3 ≈ 0.8
    # Final item confidence = min(id_conf=0.9, est_mean_conf≈0.8) = 0.8
    assert outcome.items[0].confidence == pytest.approx(0.8, abs=0.02)
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_consistency_minority_failure_tolerance(monkeypatch: pytest.MonkeyPatch) -> None:
    """1/3 calls fail → the 2 successful runs are used; outcome is NOT degraded."""
    from app.core.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("VISION_SELF_CONSISTENCY_K", "3")

    ids = [_ident("rice")]
    # First call fails, runs 2 & 3 succeed (1 failure < ceil(3/2)=2).
    responses: list[tuple[list[PortionEstimate], str] | Exception] = [
        RuntimeError("upstream blip"),
        ([_est(0, grams=160.0, confidence=0.75)], "sha-ok1"),
        ([_est(0, grams=180.0, confidence=0.85)], "sha-ok2"),
    ]
    multi = _MultiResponseEstimator(responses)

    service = RecognisePlate(
        identifier=_MockIdentifier(ids),
        estimator=multi,
    )
    outcome = await service(ctx=_make_ctx())

    assert not outcome.degraded
    assert len(outcome.items) == 1
    # Median of [160, 180] (2 successes) = (160+180)/2 = 170
    assert outcome.items[0].estimated_amount_g == pytest.approx(Decimal("170.0"))
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_consistency_majority_failure_degrades(monkeypatch: pytest.MonkeyPatch) -> None:
    """2/3 calls fail (>= ceil(3/2)=2) → outcome is degraded."""
    from app.core.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("VISION_SELF_CONSISTENCY_K", "3")

    ids = [_ident("chicken"), _ident("rice")]
    # 2 failures >= ceil(3/2)=2 → majority threshold reached.
    responses: list[tuple[list[PortionEstimate], str] | Exception] = [
        RuntimeError("fail-1"),
        RuntimeError("fail-2"),
        ([_est(0, grams=150.0), _est(1, grams=200.0)], "sha-ok"),
    ]
    multi = _MultiResponseEstimator(responses)

    service = RecognisePlate(
        identifier=_MockIdentifier(ids),
        estimator=multi,
    )
    outcome = await service(ctx=_make_ctx())

    assert outcome.degraded is True
    # Degraded items still produced (one per identification)
    assert len(outcome.items) == 2
    for it in outcome.items:
        assert it.confidence <= 0.25
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_consistency_sha_includes_all_runs(monkeypatch: pytest.MonkeyPatch) -> None:
    """Composite SHA = sha256(sha_r0 + sha_r1 + sha_r2) across all K runs."""
    import hashlib

    from app.core.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("VISION_SELF_CONSISTENCY_K", "3")

    ids = [_ident("chicken")]
    sha0, sha1, sha2 = "sha-run-0", "sha-run-1", "sha-run-2"
    responses: list[tuple[list[PortionEstimate], str] | Exception] = [
        ([_est(0, grams=120.0)], sha0),
        ([_est(0, grams=130.0)], sha1),
        ([_est(0, grams=140.0)], sha2),
    ]
    multi = _MultiResponseEstimator(responses)

    service = RecognisePlate(
        identifier=_MockIdentifier(ids, sha="sha-id"),
        estimator=multi,
    )
    outcome = await service(ctx=_make_ctx())

    # The estimate portion of the composite SHA must reflect all 3 runs.
    expected_estimate_sha = hashlib.sha256((sha0 + sha1 + sha2).encode()).hexdigest()
    # outcome.prompt_sha256 = "sha-id:{estimate_sha}"
    actual_estimate_sha = outcome.prompt_sha256.split(":", 1)[1]
    assert actual_estimate_sha == expected_estimate_sha
    get_settings.cache_clear()
