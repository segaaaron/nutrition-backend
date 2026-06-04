"""D13 runtime guard — `RecalibrationInput` rejects malformed day_index.

The `weights` series must carry a non-decreasing, non-negative UTC day index
(see `app.shared.domain.time.utc_day_index`). Out-of-order or negative inputs
typically indicate naive datetimes crossing a DST boundary; the runtime
guard catches the contract violation rather than silently biasing the OLS
slope downstream.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.nutrition.domain.recalibration import RecalibrationInput


def _kwargs(weights: list[tuple[int, float]]) -> dict:
    return dict(
        sex="male",
        weight_kg_now=Decimal("80"),
        height_cm=Decimal("180"),
        age=30,
        activity_factor=Decimal("1.55"),
        goal="maintain",
        tdee_current=2800,
        days_since_last_recalibration=30,
        weights=weights,
        kcal_in=[2500] * 14,
    )


def test_d13_accepts_monotonic_non_decreasing_indices() -> None:
    # Strictly increasing — canonical case.
    RecalibrationInput(**_kwargs([(i, 80.0) for i in range(14)]))
    # Plateaued (equal) indices are allowed: two weigh-ins on the same UTC day.
    RecalibrationInput(**_kwargs([(0, 80.0), (0, 80.1), (1, 79.9)]))


def test_d13_rejects_out_of_order_day_index() -> None:
    with pytest.raises(ValueError, match="non-decreasing"):
        RecalibrationInput(**_kwargs([(5, 80.0), (3, 79.8), (10, 79.5)]))


def test_d13_rejects_negative_day_index() -> None:
    with pytest.raises(ValueError, match="≥0"):
        RecalibrationInput(**_kwargs([(-1, 80.0), (0, 79.9)]))


def test_d13_rejects_non_int_day_index() -> None:
    with pytest.raises(ValueError, match="must be int"):
        # float disguised as day index — common when caller uses
        # (now - start).total_seconds() / 86400 instead of utc_day_index.
        RecalibrationInput(**_kwargs([(0.0, 80.0), (1.0, 79.9)]))  # type: ignore[list-item]


def test_d13_empty_weights_is_fine_for_construction() -> None:
    # Empty series is rejected later by `recalibrate()` as insufficient_data;
    # __post_init__ must not raise here — it only enforces the index contract.
    RecalibrationInput(**_kwargs([]))
