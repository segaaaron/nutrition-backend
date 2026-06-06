"""Profile bounded-context event handlers.

ADR-0028 — `onboarding_completed` flag flip trigger.

The flag is flipped from False to True when the user's FIRST plan is
generated successfully (event :class:`PlanCreated`). The previous trigger
inside :class:`CompleteOnboarding` was removed so that, from the user's
perspective, onboarding is "completed" only once a usable plan exists.

Cross-context note: subscribing the profile context to a plan-context
event is intentional per DDD — domain events are the public contract.

In-process EventBus caveat: this handler MUST be registered in BOTH the
API process (`app/main.py` lifespan) AND the Arq worker process
(`worker/main.py` `on_startup`). Plans are generated inside the worker;
without worker-side registration the flag would never flip.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.event_bus import EventBus
from app.core.logging import get_logger
from app.plan.domain.events import PlanCreated
from app.profile.infrastructure.repositories import SqlProfileRepository

log = get_logger("profile.event_handlers")

_PlanCreatedHandler = Callable[[PlanCreated], Awaitable[None]]


def make_flip_onboarding_on_plan_created(
    sessionmaker: async_sessionmaker,  # type: ignore[type-arg]
) -> _PlanCreatedHandler:
    """Build the :class:`PlanCreated` handler bound to a sessionmaker.

    Factory shape lets us inject a sessionmaker per process (API vs Arq
    worker) without reaching into module globals.

    The returned handler is **idempotent**: if the flag is already True
    (e.g. user re-generates a plan), it short-circuits with zero DB
    writes. Missing profile is logged + swallowed (never raises into the
    event bus, which would cancel sibling subscribers).
    """

    async def flip_onboarding_on_plan_created(event: PlanCreated) -> None:
        async with sessionmaker() as session:
            try:
                repo = SqlProfileRepository(session)
                profile = await repo.get(event.user_id)
                if profile is None:
                    log.warning(
                        "profile.flip_skipped_profile_missing",
                        user_id=str(event.user_id),
                        plan_id=str(event.plan_id),
                    )
                    return
                if profile.onboarding_completed:
                    # Idempotent: re-generation of plans must not write.
                    return
                profile.onboarding_completed = True
                profile.updated_at = datetime.now(tz=UTC)
                await repo.upsert(profile)
                await session.commit()
                log.info(
                    "profile.onboarding_completed_flipped",
                    user_id=str(event.user_id),
                    plan_id=str(event.plan_id),
                )
            except Exception as exc:  # noqa: BLE001 — event handler boundary
                await session.rollback()
                log.warning(
                    "profile.flip_failed",
                    user_id=str(event.user_id),
                    plan_id=str(event.plan_id),
                    error=str(exc),
                )

    return flip_onboarding_on_plan_created


def register(bus: EventBus, sessionmaker: async_sessionmaker) -> None:  # type: ignore[type-arg]
    """Wire the PlanCreated subscriber.

    Call from BOTH:
      - `app/main.py` lifespan (API process)
      - `worker/main.py` `on_startup` (Arq worker process)

    EventBus is an in-process singleton (`app/core/event_bus.py`), so
    each process owns its own instance.
    """
    bus.subscribe(PlanCreated, make_flip_onboarding_on_plan_created(sessionmaker))
