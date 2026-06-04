"""Unit — GetJobStatus use case.

Covers:
- Happy path returns the job.
- NotFoundError when repo returns None.
- Forbidden when job belongs to a different user (BOLA defence).
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.core.errors import Forbidden, NotFoundError
from app.vision.application.get_job_status import GetJobStatus
from app.vision.domain.entities import VisionJob


def _job(owner_id):
    return VisionJob(
        id=uuid4(),
        user_id=owner_id,
        status="completed",
        image_sha256="a" * 64,
        created_at=datetime.now(UTC),
    )


@pytest.mark.asyncio
async def test_returns_job_for_owner():
    user_id = uuid4()
    job = _job(user_id)
    repo = MagicMock()
    repo.get = AsyncMock(return_value=job)
    uc = GetJobStatus(repo=repo)

    result = await uc(job_id=job.id, user_id=user_id)

    assert result is job
    repo.get.assert_awaited_once_with(job.id)


@pytest.mark.asyncio
async def test_not_found_when_repo_returns_none():
    repo = MagicMock()
    repo.get = AsyncMock(return_value=None)
    uc = GetJobStatus(repo=repo)

    with pytest.raises(NotFoundError, match="vision_job:"):
        await uc(job_id=uuid4(), user_id=uuid4())


@pytest.mark.asyncio
async def test_forbidden_when_job_belongs_to_other_user():
    owner = uuid4()
    intruder = uuid4()
    repo = MagicMock()
    repo.get = AsyncMock(return_value=_job(owner))
    uc = GetJobStatus(repo=repo)

    with pytest.raises(Forbidden, match="not_owner"):
        await uc(job_id=uuid4(), user_id=intruder)
