"""Patrón #5 — invariant: at most ONE live subscription per user.

Regression for the ``HandleWebhook`` branch on ``subscription.created`` /
``checkout.session.completed`` events. Previously the use case minted a
fresh ``uuid4()`` per webhook → ``ON CONFLICT (id) DO UPDATE`` never
fired → two parallel webhooks for the same user produced two rows with
``status='active'``. The fix reuses the existing row id when present
and treats DB-level UNIQUE violations from the partial index
``uq_subscriptions_one_live_per_user`` (migration 0016) as idempotent
no-ops.
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from sqlalchemy.exc import IntegrityError

from app.billing.domain import (
    BillingProvider,
    Plan,
    Subscription,
    SubscriptionStatus,
)
from app.billing.use_cases import HandleWebhook


class _StubRepo:
    """In-memory billing repository for use-case tests.

    Mirrors the partial UNIQUE invariant of migration 0016 so the test
    can prove the application code does NOT rely on the DB to dedupe
    on the happy path (it reuses the existing row id) AND that it does
    gracefully recover when the DB enforces the invariant on a race.
    """

    def __init__(self, *, raise_on_second_upsert: bool = False) -> None:
        self.subs: dict[UUID, Subscription] = {}
        self.events: set[str] = set()
        self._raise_on_second = raise_on_second_upsert
        self._upsert_calls = 0

    async def get_subscription(self, user_id: UUID) -> Subscription | None:
        for s in self.subs.values():
            if s.user_id == user_id:
                return s
        return None

    async def upsert_subscription(self, sub: Subscription) -> None:
        self._upsert_calls += 1
        if (
            self._raise_on_second
            and self._upsert_calls >= 2
            and sub.status
            in (
                SubscriptionStatus.TRIALING,
                SubscriptionStatus.ACTIVE,
                SubscriptionStatus.PAST_DUE,
            )
        ):
            # Simulate the partial UNIQUE index firing on a concurrent
            # webhook race.
            raise IntegrityError("INSERT", {}, Exception("uq_one_live"))
        self.subs[sub.id] = sub

    async def insert_webhook_event(
        self, *, event_id: str, provider: str, payload: dict
    ) -> bool:
        if event_id in self.events:
            return False
        self.events.add(event_id)
        return True


class _StubBus:
    def __init__(self) -> None:
        self.published: list = []

    async def publish(self, event) -> None:
        self.published.append(event)

    async def publish_many(self, events) -> None:
        self.published.extend(events)


def _checkout_event(*, event_id: str, user_id: UUID, plan: str = "premium") -> dict:
    return {
        "id": event_id,
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "id": "sub_stripe_1",
                "metadata": {"user_id": str(user_id), "plan": plan},
            }
        },
    }


@pytest.mark.asyncio
async def test_replay_same_webhook_is_deduped_at_event_layer() -> None:
    repo = _StubRepo()
    bus = _StubBus()
    uc = HandleWebhook(repo=repo, bus=bus, provider=BillingProvider.STRIPE)
    user_id = uuid4()
    event = _checkout_event(event_id="evt_1", user_id=user_id)

    out_1 = await uc(event=event)
    out_2 = await uc(event=event)

    assert out_1["processed"] is True
    assert out_2["duplicate"] is True
    # Single live row → invariant holds.
    live = [
        s
        for s in repo.subs.values()
        if s.status
        in (
            SubscriptionStatus.TRIALING,
            SubscriptionStatus.ACTIVE,
            SubscriptionStatus.PAST_DUE,
        )
        and s.user_id == user_id
    ]
    assert len(live) == 1


@pytest.mark.asyncio
async def test_two_distinct_create_events_reuse_existing_subscription_id() -> None:
    """Two ``checkout.session.completed`` events for the same user (e.g.
    Stripe + a manual replay with a different event_id) must NOT mint a
    second subscription row.
    """
    repo = _StubRepo()
    bus = _StubBus()
    uc = HandleWebhook(repo=repo, bus=bus, provider=BillingProvider.STRIPE)
    user_id = uuid4()

    await uc(event=_checkout_event(event_id="evt_1", user_id=user_id))
    await uc(event=_checkout_event(event_id="evt_2", user_id=user_id))

    assert len(repo.subs) == 1
    sub = next(iter(repo.subs.values()))
    assert sub.user_id == user_id
    assert sub.status == SubscriptionStatus.ACTIVE


@pytest.mark.asyncio
async def test_db_unique_violation_is_swallowed_as_idempotent_noop() -> None:
    """When the partial UNIQUE index in migration 0016 fires on a race
    (another concurrent transaction won the insert), ``HandleWebhook``
    MUST return a structured ``duplicate_live_subscription`` outcome
    rather than raising a 500. Defends the public webhook endpoint
    against provider retries during a race window.
    """
    # Pre-populate so first call simulates the race winner; second call
    # raises IntegrityError when the use case tries its own insert.
    repo = _StubRepo(raise_on_second_upsert=True)
    bus = _StubBus()
    uc = HandleWebhook(repo=repo, bus=bus, provider=BillingProvider.STRIPE)
    user_id = uuid4()

    # First webhook (winner) — succeeds.
    await uc(event=_checkout_event(event_id="evt_1", user_id=user_id))
    # Second webhook (race loser) — simulate by clearing event_id dedupe
    # so the use case actually tries the upsert path again.
    repo.events.clear()
    # Force the use case down the "no existing live sub" branch by
    # temporarily hiding the existing row — easiest is to wipe and re-add
    # under a different uuid that will not be matched by get_subscription.
    # Simpler: drop the in-memory rows AFTER ``upsert_calls`` counter
    # already advanced, so next upsert is the "second" and raises.
    out = await uc(event=_checkout_event(event_id="evt_2", user_id=user_id))

    assert out.get("reason") == "duplicate_live_subscription"
