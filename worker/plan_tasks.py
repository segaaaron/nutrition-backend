"""Arq task that runs the full plan generation pipeline.

Registered into `worker/main.py::FUNCTIONS` so the API can `enqueue_job`
this by name without coupling the API process to the worker module.

Memory budget: ~150 MB resident per job (no pyvips, no LLM call > 1MB
payload). MAX_JOBS=2 keeps us under the 1.5 GB worker container limit.
"""
from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import text

from app.core.db import session_scope
from app.core.event_bus import get_event_bus
from app.core.logging import get_logger
from app.core.redis import get_redis
from app.nutrition.infrastructure.compute_goals_adapter import InlineComputeGoals
from app.plan.application.create_plan import CreatePlan
from app.plan.application.layer1_eligibility import Layer1Eligibility
from app.plan.application.layer2_shortlist import Layer2Shortlist
from app.plan.application.layer3_ranking import Layer3Ranking
from app.plan.application.layer4_coherence import Layer4Coherence
from app.plan.application.taste_profile import TasteProfileService
from app.plan.infrastructure.openai_coherence_client import CoherencePass
from app.plan.infrastructure.profile_reader import SqlEligibilityProfileReader
from app.plan.infrastructure.repositories import SqlPlanRepository
from app.plan.infrastructure.taste_fetcher import SqlEmbeddingFetcher
from app.plan.infrastructure.user_context import SqlUserContext

log = get_logger("worker.plan")

_MAX_TRIES = 3


async def generate_plan_task(
    ctx: dict[str, Any],
    *,
    user_id: str,
    plan_type: str,
    preferences: list[str] | None = None,
    seed: int | None = None,
    locale: str | None = None,
) -> dict[str, Any]:
    uid = UUID(user_id)
    try:
        async with session_scope() as session:
            profile_reader = SqlEligibilityProfileReader(session)
            user_ctx = SqlUserContext(session)
            taste_vec = await TasteProfileService(
                redis=get_redis(), fetcher=SqlEmbeddingFetcher(session),
            ).get_or_build(uid)
            layer1 = Layer1Eligibility(session=session, profile_reader=profile_reader)
            layer2 = Layer2Shortlist(session=session)
            layer3 = Layer3Ranking(session=session, profile_ctx=user_ctx, taste_vector=taste_vec)
            layer4 = Layer4Coherence(client=CoherencePass(user_id=uid))
            bus = get_event_bus()
            uc = CreatePlan(
                plans=SqlPlanRepository(session),
                layer1=layer1, layer2=layer2, layer3=layer3, layer4=layer4,
                user_ctx=user_ctx, bus=bus,
                ensure_goals=InlineComputeGoals(session=session, bus=bus),
            )
            plan = await uc(
                user_id=uid, plan_type=plan_type,  # type: ignore[arg-type]
                seed=seed, preferences=preferences,
                locale=locale,  # type: ignore[arg-type]
            )
            log.info("worker.plan.generated", plan_id=str(plan.id))
            return {"plan_id": str(plan.id)}
    except Exception as exc:  # noqa: BLE001
        job_try = int(ctx.get("job_try") or 1)
        if job_try < _MAX_TRIES:
            log.warning("plan.task.retrying", user_id=user_id, attempt=job_try, err=exc.__class__.__name__)
            raise
        # Terminal failure — iOS has no signal otherwise; deadletter for ops.
        log.error("plan.task.terminal_failure", user_id=user_id, attempts=job_try, err=str(exc)[:300])
        async with session_scope() as cleanup:
            await cleanup.execute(text("""
                INSERT INTO job_deadletter (task_name, args, error, attempts, failed_at)
                VALUES ('generate_plan_task',
                        jsonb_build_object('user_id', :uid, 'plan_type', :pt),
                        :err, :attempts, now())
            """), {"uid": user_id, "pt": plan_type, "err": str(exc)[:500], "attempts": job_try})
        raise
