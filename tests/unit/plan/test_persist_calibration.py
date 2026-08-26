"""Unit — C18: persist_calibration field in AdjustPortionRequest schema."""

from __future__ import annotations

import pytest
from pydantic import ValidationError as PydValidationError

from app.plan.presentation.schemas import AdjustPortionRequest
from decimal import Decimal


def test_persist_calibration_defaults_true():
    r = AdjustPortionRequest.model_validate_json('{"user_factor": 0.75}')
    assert r.persist_calibration is True


def test_persist_calibration_false_accepted():
    r = AdjustPortionRequest.model_validate_json(
        '{"user_factor": 0.75, "persist_calibration": false}'
    )
    assert r.persist_calibration is False
    assert r.user_factor == Decimal("0.75")


def test_persist_calibration_true_explicit():
    r = AdjustPortionRequest.model_validate_json(
        '{"user_factor": 1.0, "persist_calibration": true}'
    )
    assert r.persist_calibration is True


def test_extra_fields_rejected():
    with pytest.raises(PydValidationError):
        AdjustPortionRequest.model_validate_json(
            '{"user_factor": 0.75, "persist_calibration": false, "extra": 1}'
        )
