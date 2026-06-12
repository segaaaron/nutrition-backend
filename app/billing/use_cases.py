"""Billing use cases — trial, checkout, cancel, webhook, entitlements."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.billing.domain import (
    BillingProvider,
    Plan,
    Subscription,
    SubscriptionCancelled,
    SubscriptionCreated,
    SubscriptionStatus,
    SubscriptionUpdated,
    TrialStarted,
)
from app.billing.gateways import gateway_for_country
from app.billing.pricing import ENTITLEMENTS
from app.billing.repository import SqlBillingRepository
from app.core.errors import ConflictError, NotFoundError
from app.core.event_bus import EventBus


@dataclass(slots=True)
class StartTrial:
    repo: SqlBillingRepository
    bus: EventBus

    async def __call__(self, *, user_id: UUID, plan: Plan = Plan.PREMIUM) -> Subscription:
        existing = await self.repo.get_subscription(user_id)
        if existing and existing.status not in (
            SubscriptionStatus.CANCELLED,
            SubscriptionStatus.INCOMPLETE,
        ):
            raise ConflictError(detail="already_subscribed")
        trial_end = datetime.now(UTC) + timedelta(days=14)
        sub = Subscription(
            id=uuid4(),
            user_id=user_id,
            plan=plan,
            status=SubscriptionStatus.TRIALING,
            provider=BillingProvider.STRIPE,
            provider_subscription_id=None,
            current_period_end=trial_end,
            cancel_at_period_end=False,
            trial_end=trial_end,
        )
        await self.repo.upsert_subscription(sub)
        await self.bus.publish(
            TrialStarted(
                user_id=user_id,
                plan=plan.value,
                trial_end=trial_end,
            )
        )
        return sub


@dataclass(slots=True)
class CreateCheckout:
    """Returns a hosted checkout URL from the country-appropriate gateway."""

    session: AsyncSession

    async def __call__(
        self,
        *,
        user_id: UUID,
        plan: Plan,
        success_url: str,
        cancel_url: str,
    ) -> dict:
        r = (
            (
                await self.session.execute(
                    text(
                        """
            SELECT u.email, COALESCE(p.country, 'US') AS country
              FROM users u LEFT JOIN user_profiles p ON p.user_id = u.id
             WHERE u.id = :uid
        """
                    ),
                    {"uid": str(user_id)},
                )
            )
            .mappings()
            .first()
        )
        if not r:
            raise NotFoundError(detail="user_not_found")
        gw = gateway_for_country(r["country"])
        return await gw.create_checkout(
            user_id=user_id,
            email=r["email"],
            plan=plan,
            country=r["country"],
            success_url=success_url,
            cancel_url=cancel_url,
        )


@dataclass(slots=True)
class CancelSubscription:
    repo: SqlBillingRepository
    bus: EventBus

    async def __call__(self, *, user_id: UUID) -> Subscription:
        sub = await self.repo.get_subscription(user_id)
        if sub is None:
            raise NotFoundError(detail="no_subscription")
        if sub.status == SubscriptionStatus.CANCELLED:
            raise ConflictError(detail="already_cancelled")
        if sub.provider_subscription_id:
            gw = gateway_for_country("US" if sub.provider == BillingProvider.STRIPE else "MX")
            await gw.cancel_subscription(provider_sub_id=sub.provider_subscription_id)
        sub.cancel_at_period_end = True
        await self.repo.upsert_subscription(sub)
        await self.bus.publish(
            SubscriptionCancelled(
                user_id=user_id,
                at=datetime.now(UTC),
            )
        )
        return sub


@dataclass(slots=True)
class GetSubscription:
    repo: SqlBillingRepository

    async def __call__(self, user_id: UUID) -> dict:
        sub = await self.repo.get_subscription(user_id)
        if sub is None:
            ent = ENTITLEMENTS[Plan.FREE]
            return {"plan": "free", "status": "none", "entitlements": ent}
        return {
            "plan": sub.plan.value,
            "status": sub.status.value,
            "provider": sub.provider.value,
            "current_period_end": (
                sub.current_period_end.isoformat() if sub.current_period_end else None
            ),
            "cancel_at_period_end": sub.cancel_at_period_end,
            "trial_end": sub.trial_end.isoformat() if sub.trial_end else None,
            "entitlements": ENTITLEMENTS[sub.plan],
        }


@dataclass(slots=True)
class HandleWebhook:
    """Idempotent webhook processing. Routes Stripe + Mercado Pago events
    into common subscription/payment domain events.
    """

    repo: SqlBillingRepository
    bus: EventBus
    provider: BillingProvider

    async def __call__(self, *, event: dict) -> dict:
        # Fallback when the provider omits `id`: deterministic hash of the
        # payload, NOT a timestamp. A timestamp-based synthetic id made every
        # replay of the same id-less webhook look unique → duplicate
        # processing. Same payload now always maps to the same event_id, so
        # the insert_webhook_event dedup still holds.
        event_id = event.get("id") or event.get("data", {}).get("id")
        if not event_id:
            digest = hashlib.sha256(
                json.dumps(event, sort_keys=True, default=str).encode()
            ).hexdigest()[:32]
            event_id = f"{self.provider.value}:sha:{digest}"
        ok = await self.repo.insert_webhook_event(
            event_id=event_id,
            provider=self.provider.value,
            payload=event,
        )
        if not ok:
            return {"duplicate": True, "event_id": event_id}
        etype = event.get("type") or event.get("action") or ""
        user_id = event.get("data", {}).get("object", {}).get("metadata", {}).get("user_id")
        if not user_id:
            return {"processed": False, "reason": "no_user_id_in_metadata"}
        uid = UUID(user_id)
        if "subscription.created" in etype or "checkout.session.completed" in etype:
            sub_obj = event.get("data", {}).get("object", {})
            plan_str = sub_obj.get("metadata", {}).get("plan", "premium")
            # Patrón #5 — invariante post-mutación: a user MUST have at most
            # one live subscription row (statuses trialing/active/past_due).
            # Previously this branch minted ``uuid4()`` on every event so the
            # ``ON CONFLICT (id) DO UPDATE`` in ``upsert_subscription`` never
            # fired — two concurrent ``subscription.created`` webhooks for
            # the same user produced two ``status='active'`` rows. We now
            # reuse the existing row id when present and rely on the
            # partial UNIQUE index ``uq_subscriptions_one_live_per_user``
            # (migration 0016) as last-line defence for the race window
            # between read and write.
            existing = await self.repo.get_subscription(uid)
            sub = Subscription(
                id=existing.id if existing is not None else uuid4(),
                user_id=uid,
                plan=Plan(plan_str),
                status=SubscriptionStatus.ACTIVE,
                provider=self.provider,
                provider_subscription_id=sub_obj.get("subscription") or sub_obj.get("id"),
                current_period_end=None,
                cancel_at_period_end=False,
                trial_end=None,
            )
            from sqlalchemy.exc import IntegrityError as _IntegrityError

            try:
                await self.repo.upsert_subscription(sub)
            except _IntegrityError:
                # UNIQUE violation on (user_id) WHERE status IN
                # ('trialing','active','past_due'): a concurrent webhook
                # already promoted the user to active. The other transaction
                # wins; this one is a redundant replay. Idempotent no-op —
                # the webhook_events row was already inserted above so
                # downstream retries are deduped at that layer too.
                return {"processed": False, "reason": "duplicate_live_subscription", "event_id": event_id}
            await self.bus.publish(
                SubscriptionCreated(
                    user_id=uid,
                    plan=plan_str,
                    provider=self.provider.value,
                )
            )
        elif "subscription.updated" in etype:
            existing = await self.repo.get_subscription(uid)
            if existing:
                existing.status = SubscriptionStatus.ACTIVE
                await self.repo.upsert_subscription(existing)
                await self.bus.publish(
                    SubscriptionUpdated(
                        user_id=uid,
                        plan=existing.plan.value,
                        status="active",
                    )
                )
        elif "subscription.deleted" in etype or "cancelled" in etype:
            existing = await self.repo.get_subscription(uid)
            if existing:
                existing.status = SubscriptionStatus.CANCELLED
                await self.repo.upsert_subscription(existing)
                await self.bus.publish(
                    SubscriptionCancelled(
                        user_id=uid,
                        at=datetime.now(UTC),
                    )
                )
        return {"processed": True, "event_id": event_id, "type": etype}


# --- Entitlements middleware helper ---


async def get_entitlements(session: AsyncSession, user_id: UUID) -> dict:
    sub = await SqlBillingRepository(session).get_subscription(user_id)
    if sub is None or sub.status in (
        SubscriptionStatus.CANCELLED,
        SubscriptionStatus.INCOMPLETE,
    ):
        return ENTITLEMENTS[Plan.FREE]
    return ENTITLEMENTS[sub.plan]
