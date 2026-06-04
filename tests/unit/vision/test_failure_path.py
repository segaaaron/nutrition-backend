"""Unit — coverage gap: provider exception triggers `mark_failed` + emits
`VisionJobFailed` + notifies the client. Ensures the error handler in
`ProcessVisionJob.__call__` is exercised.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.core.errors import UpstreamError
from app.vision.application.process_vision_job import ProcessVisionJob
from app.vision.domain.entities import VisionJob
from app.vision.domain.events import VisionJobFailed


@pytest.mark.asyncio
async def test_provider_failure_marks_job_failed() -> None:
    job_id = uuid4()
    user_id = uuid4()
    sha = "f" * 64

    repo = MagicMock()
    repo.mark_running = AsyncMock()
    repo.mark_completed = AsyncMock()
    repo.mark_failed = AsyncMock()
    repo.get = AsyncMock(
        return_value=VisionJob(
            id=job_id,
            user_id=user_id,
            image_sha256=sha,
            status="running",
            created_at=datetime.now(UTC),
        )
    )
    repo.find_recent_completed_by_sha = AsyncMock(return_value=None)

    provider = MagicMock()
    provider.recognise = AsyncMock(side_effect=UpstreamError("openai_down"))

    matcher = MagicMock()
    matcher.match = AsyncMock()
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
        session=MagicMock(execute=AsyncMock()),
    )

    with pytest.raises(UpstreamError):
        await uc(
            job_id=job_id,
            user_id=user_id,
            meal_time="lunch",
            image_bytes=b"img",
            mime="image/jpeg",
            locale="es",
            region="latam",
        )

    repo.mark_failed.assert_awaited_once()
    repo.mark_completed.assert_not_called()
    # VisionJobFailed published.
    failed_events = [
        c.args[0] for c in bus.publish.await_args_list if isinstance(c.args[0], VisionJobFailed)
    ]
    assert len(failed_events) == 1
    notifier.notify.assert_awaited()
