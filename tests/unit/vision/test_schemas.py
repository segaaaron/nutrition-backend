"""Unit — vision presentation Pydantic schemas.

Pure value-object tests: defaults, type coercion, extra=forbid for
EditDetectedItemRequest.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError as PydValidationError

from app.vision.presentation.schemas import (
    DetectedItemDto,
    EditDetectedItemRequest,
    JobStatusResponse,
    SubmitPhotoResponse,
)


def test_submit_response_default_status():
    job_id = uuid4()
    r = SubmitPhotoResponse(job_id=job_id)
    assert r.job_id == job_id
    assert r.status == "queued"


def test_detected_item_dto_optional_match_fields_default_none():
    d = DetectedItemDto(
        name="oat",
        estimated_amount_g=Decimal("60"),
        kcal=230,
        protein_g=7,
        carbs_g=40,
        fat_g=4,
        confidence=0.9,
    )
    assert d.matched_food_id is None
    assert d.match_method is None


def test_detected_item_dto_with_matched_food():
    fid = uuid4()
    d = DetectedItemDto(
        name="banana",
        estimated_amount_g=Decimal("100"),
        kcal=89,
        protein_g=1,
        carbs_g=23,
        fat_g=0,
        confidence=0.85,
        matched_food_id=fid,
        match_method="trigram",
    )
    assert d.matched_food_id == fid
    assert d.match_method == "trigram"


def test_job_status_response_defaults():
    r = JobStatusResponse(job_id=uuid4(), status="queued")
    assert r.items == []
    assert r.error_code is None
    assert r.created_at is None


def test_job_status_response_with_items():
    item = DetectedItemDto(
        name="x",
        estimated_amount_g=Decimal("1"),
        kcal=1,
        protein_g=0,
        carbs_g=0,
        fat_g=0,
        confidence=0.5,
    )
    now = datetime.now(UTC)
    r = JobStatusResponse(
        job_id=uuid4(),
        status="completed",
        items=[item],
        created_at=now,
        completed_at=now,
    )
    assert len(r.items) == 1
    assert r.completed_at == now


def test_edit_request_forbids_extra_fields():
    with pytest.raises(PydValidationError):
        EditDetectedItemRequest(
            detected_name="rice",
            corrected_food_id=uuid4(),
            corrected_amount_g=Decimal("100"),
            extra_unknown_field="x",  # type: ignore[call-arg]
        )


def test_edit_request_minimal_body():
    r = EditDetectedItemRequest(detected_name="rice")
    assert r.corrected_food_id is None
    assert r.corrected_amount_g is None
