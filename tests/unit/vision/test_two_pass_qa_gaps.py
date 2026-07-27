"""QA gate — two-pass vision pipeline (E2) edge cases.

Tests marked ``xfail(strict=True)`` document CONFIRMED defects found during the
E2 QA audit (2026-07-25).  They are expected to fail today; when the defect is
fixed the strict marker turns the XPASS into a failure so the marker gets
removed together with the fix.  Every other test locks in behaviour that is
correct today and must not regress.

All tests use mocks — no DB, no network.
"""
from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.vision.application.process_vision_job import ProcessVisionJob
from app.vision.application.recognise_plate import (
    RecognisePlate,
    RecognitionContext,
    _median_decimal,
)
from app.vision.domain.entities import VisionJob
from app.vision.domain.value_objects import FoodIdentification, PortionEstimate

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ident(
    name: str,
    *,
    confidence: float = 0.9,
    bbox: tuple[float, float, float, float] | None = None,
) -> FoodIdentification:
    return FoodIdentification(
        name=name,
        confidence=confidence,
        group="protein",
        role="main",
        prep_method="grilled",
        count=1,
        portion_kind="a_granel",
        bbox=bbox,
    )


def _est(index: int, *, grams: float = 150.0, confidence: float = 0.8) -> PortionEstimate:
    return PortionEstimate(
        index=index,
        estimated_amount_g=Decimal(str(grams)),
        kcal=200,
        protein_g=30,
        carbs_g=5,
        fat_g=7,
        confidence=confidence,
    )


def _ctx() -> RecognitionContext:
    return RecognitionContext(
        image_bytes=b"fake-image",
        mime="image/jpeg",
        user_id=uuid4(),
        locale="es",
        region="MX",
    )


class _Identifier:
    def __init__(self, items: list[FoodIdentification], sha: str = "IDSHA") -> None:
        self._items = items
        self._sha = sha

    async def identify(self, **_kw: object) -> tuple[list[FoodIdentification], str]:
        return self._items, self._sha

    def identification_prompt_sha256(self, *, locale: str, region: str) -> str:
        return self._sha


class _Estimator:
    def __init__(self, estimates: list[PortionEstimate], sha: str = "ESTSHA") -> None:
        self._estimates = estimates
        self._sha = sha

    async def estimate(self, **_kw: object) -> tuple[list[PortionEstimate], str]:
        return self._estimates, self._sha

    def estimation_prompt_sha256(self, *, locale: str, region: str) -> str:
        return self._sha


# ---------------------------------------------------------------------------
# _median_decimal — pure function contract
# ---------------------------------------------------------------------------


def test_median_decimal_odd_and_even_lengths() -> None:
    """Even-length median = mean of the two central values (documented contract)."""
    assert _median_decimal([Decimal("100"), Decimal("150"), Decimal("200")]) == Decimal("150")
    assert _median_decimal([Decimal("160"), Decimal("180")]) == Decimal("170")
    assert _median_decimal([Decimal("100.1"), Decimal("100.2")]) == Decimal("100.15")
    assert _median_decimal([Decimal("42")]) == Decimal("42")


def test_median_decimal_is_order_independent() -> None:
    """Aggregation must not depend on which concurrent run finished first."""
    a = _median_decimal([Decimal("200"), Decimal("100"), Decimal("150")])
    b = _median_decimal([Decimal("150"), Decimal("200"), Decimal("100")])
    assert a == b == Decimal("150")


# ---------------------------------------------------------------------------
# Confirmed defects
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_out_of_range_estimate_index_does_not_pollute_conf_avg() -> None:
    """A hallucinated index (7 with only 2 identifications) must not be averaged in.

    Repro: identifications=[a, b]; estimates for indices 0 (0.9), 1 (0.9) and a
    bogus index 7 (0.1).  estimation_conf_avg should be 0.9 but is 0.633 because
    the orphan estimate is counted.  _merge() then drops it without telemetry.
    """
    service = RecognisePlate(
        identifier=_Identifier([_ident("a"), _ident("b")]),
        estimator=_Estimator([_est(0, confidence=0.9), _est(1, confidence=0.9), _est(7, confidence=0.1)]),
    )
    outcome = await service(ctx=_ctx())

    assert len(outcome.items) == 2
    assert outcome.estimation_conf_avg == pytest.approx(0.9)


@pytest.mark.asyncio
@pytest.mark.xfail(
    strict=True,
    reason="E2 defect: FoodIdentification.bbox is never propagated to "
    "DetectedFoodItem, so the two-pass path loses the BE-5 iOS annotation box.",
)
async def test_bbox_survives_two_pass_merge() -> None:
    """bbox is part of the identification contract; merge must carry it forward."""
    service = RecognisePlate(
        identifier=_Identifier([_ident("a", bbox=(0.1, 0.2, 0.3, 0.4))]),
        estimator=_Estimator([_est(0)]),
    )
    outcome = await service(ctx=_ctx())

    assert outcome.items[0].bbox == (0.1, 0.2, 0.3, 0.4)


@pytest.mark.asyncio
async def test_hint_source_failure_is_best_effort() -> None:
    """Hints are documented as best-effort — a hint-source error must not fail the job."""

    class _BoomHints(RecognisePlate):
        async def _load_hints(self, ids: object) -> dict:  # type: ignore[override]
            raise RuntimeError("hint source down")

    service = _BoomHints(
        identifier=_Identifier([_ident("a")]),
        estimator=_Estimator([_est(0)]),
    )
    outcome = await service(ctx=_ctx())

    assert not outcome.degraded
    assert len(outcome.items) == 1


@pytest.mark.asyncio
async def test_duplicate_estimate_index_does_not_silently_win() -> None:
    """Two estimates for the same index must not resolve to 'whatever came last'."""
    service = RecognisePlate(
        identifier=_Identifier([_ident("a")]),
        estimator=_Estimator([_est(0, grams=100.0), _est(0, grams=900.0)]),
    )
    outcome = await service(ctx=_ctx())

    assert outcome.items[0].estimated_amount_g != Decimal("900.0")


@pytest.mark.asyncio
async def test_two_pass_persisted_sha_matches_cache_lookup_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The sha persisted on the job must be the sha the cache looks up.

    Otherwise the SHA-dedup and pHash caches degrade to a 0% hit rate and every
    repeat photo pays the full 2-call (or K+1-call) LLM cost.
    """
    from app.core.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("VISION_TWO_PASS_ENABLED", "true")
    monkeypatch.setenv("VISION_CASCADE_ENABLED", "false")
    monkeypatch.setenv("VISION_SELF_CONSISTENCY_K", "1")
    try:
        job_id, user_id = uuid4(), uuid4()

        repo = MagicMock()
        repo.mark_running = AsyncMock()
        repo.mark_completed = AsyncMock()
        repo.mark_failed = AsyncMock()
        repo.get = AsyncMock(
            return_value=VisionJob(
                id=job_id,
                user_id=user_id,
                image_sha256="c" * 64,
                status="running",
                created_at=datetime.now(UTC),
            )
        )
        repo.find_recent_completed_by_sha = AsyncMock(return_value=None)

        provider = MagicMock()
        provider.current_prompt_sha256 = MagicMock(return_value="SINGLE_PASS_SHA")
        # Two-pass prompt SHA methods — must return stable strings so the composite
        # cache lookup key "IDSHA:ESTSHA" matches what RecognisePlate persists.
        provider.identification_prompt_sha256 = MagicMock(return_value="IDSHA")
        provider.estimation_prompt_sha256 = MagicMock(return_value="ESTSHA")
        provider.identify = AsyncMock(return_value=([_ident("avena")], "IDSHA"))
        provider.estimate = AsyncMock(return_value=([_est(0)], "ESTSHA"))
        provider.recognise = AsyncMock()

        matcher = MagicMock()
        matcher.match = AsyncMock(return_value=(uuid4(), "avena", "trigram", None))

        session = MagicMock()
        _res = MagicMock()
        _res.all.return_value = []
        session.execute = AsyncMock(return_value=_res)

        notifier = MagicMock()
        notifier.notify = AsyncMock()
        bus = MagicMock()
        bus.publish = AsyncMock()

        uc = ProcessVisionJob(
            repo=repo,
            provider=provider,
            matcher=matcher,
            notifier=notifier,
            bus=bus,
            session=session,
        )
        await uc(
            job_id=job_id,
            user_id=user_id,
            meal_time="lunch",
            image_bytes=b"some-image",
            mime="image/jpeg",
            locale="es",
            region="latam",
        )

        lookup_sha = repo.find_recent_completed_by_sha.await_args.kwargs[
            "current_prompt_sha256"
        ]
        persisted_sha = repo.mark_completed.await_args.kwargs["prompt_sha256"]
        assert persisted_sha == lookup_sha
    finally:
        get_settings.cache_clear()


# ---------------------------------------------------------------------------
# Behaviour that is correct today — lock it in
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_flag_off_uses_single_pass_only(monkeypatch: pytest.MonkeyPatch) -> None:
    """With VISION_TWO_PASS_ENABLED=false the two-pass adapters must never be called."""
    from app.core.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("VISION_TWO_PASS_ENABLED", "false")
    monkeypatch.setenv("VISION_CASCADE_ENABLED", "false")
    try:
        job_id, user_id = uuid4(), uuid4()

        repo = MagicMock()
        repo.mark_running = AsyncMock()
        repo.mark_completed = AsyncMock()
        repo.mark_failed = AsyncMock()
        repo.get = AsyncMock(
            return_value=VisionJob(
                id=job_id,
                user_id=user_id,
                image_sha256="d" * 64,
                status="running",
                created_at=datetime.now(UTC),
            )
        )
        repo.find_recent_completed_by_sha = AsyncMock(return_value=None)

        provider = MagicMock()
        provider.current_prompt_sha256 = MagicMock(return_value="SINGLE_PASS_SHA")
        provider.identify = AsyncMock()
        provider.estimate = AsyncMock()
        provider.recognise = AsyncMock(return_value=([], "SINGLE_PASS_SHA"))

        matcher = MagicMock()
        matcher.match = AsyncMock(return_value=(None, None, "unmatched", None))

        session = MagicMock()
        _res = MagicMock()
        _res.all.return_value = []
        session.execute = AsyncMock(return_value=_res)

        notifier = MagicMock()
        notifier.notify = AsyncMock()
        bus = MagicMock()
        bus.publish = AsyncMock()

        uc = ProcessVisionJob(
            repo=repo,
            provider=provider,
            matcher=matcher,
            notifier=notifier,
            bus=bus,
            session=session,
        )
        await uc(
            job_id=job_id,
            user_id=user_id,
            meal_time="lunch",
            image_bytes=b"some-image",
            mime="image/jpeg",
            locale="es",
            region="latam",
        )

        provider.recognise.assert_awaited_once()
        provider.identify.assert_not_called()
        provider.estimate.assert_not_called()
        assert repo.mark_completed.await_args.kwargs["prompt_sha256"] == "SINGLE_PASS_SHA"
    finally:
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_degraded_items_stay_below_escalation_threshold() -> None:
    """_degrade() confidence must stay under _ESCALATE_MIN_ITEM_CONF (0.35).

    This is the contract that makes a Call-2 failure recoverable: the pipeline
    must see the plate as low-confidence and escalate instead of persisting the
    placeholder 100 g / 0 kcal rows.
    """
    from app.vision.application.process_vision_job import (
        _ESCALATE_MIN_ITEM_CONF,
        needs_full_model,
    )

    service = RecognisePlate(
        identifier=_Identifier([_ident("a"), _ident("b")]),
        estimator=_Estimator([]),
    )
    outcome = await service(ctx=_ctx())

    assert outcome.degraded is True
    for it in outcome.items:
        assert it.confidence < _ESCALATE_MIN_ITEM_CONF
    escalate, reason = needs_full_model(list(outcome.items))
    assert escalate is True
    assert reason == "very_low_item_confidence"


@pytest.mark.asyncio
async def test_degraded_items_carry_zero_kcal_placeholder() -> None:
    """Explicit: degradation emits 100 g / 0 kcal rows.

    These are physically impossible and MUST be repaired by macro grounding or
    escalation before persistence.  If this assertion ever changes, revisit
    apply_group_fallback's `it.kcal <= 0` acceptance branch.
    """
    items = RecognisePlate._degrade([_ident("arroz")])
    assert items[0].estimated_amount_g == Decimal("100")
    assert items[0].kcal == 0
    assert items[0].protein_g == items[0].carbs_g == items[0].fat_g == 0
    assert items[0].matched_food_id is None
    assert items[0].inferred is False  # must stay eligible for group fallback
