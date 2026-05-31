"""Polling endpoint use case."""
from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from app.core.errors import Forbidden, NotFoundError
from app.vision.domain.entities import VisionJob
from app.vision.domain.ports import VisionJobRepository


@dataclass(slots=True)
class GetJobStatus:
    repo: VisionJobRepository

    async def __call__(self, *, job_id: UUID, user_id: UUID) -> VisionJob:
        job = await self.repo.get(job_id)
        if job is None:
            raise NotFoundError(f"vision_job:{job_id}")
        if job.user_id != user_id:
            raise Forbidden("not_owner")
        return job
