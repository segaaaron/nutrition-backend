"""Billing SQL repository."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.billing.domain import (
    BillingProvider,
    Plan,
    Subscription,
    SubscriptionStatus,
)


class SqlBillingRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.s = session

    async def get_subscription(self, user_id: UUID) -> Subscription | None:
        r = (
            (
                await self.s.execute(
                    text(
                        """
            SELECT id, user_id, plan, status, provider, provider_subscription_id,
                   current_period_end, cancel_at_period_end, trial_end
              FROM subscriptions WHERE user_id = :uid
             ORDER BY created_at DESC LIMIT 1
        """
                    ),
                    {"uid": str(user_id)},
                )
            )
            .mappings()
            .first()
        )
        if not r:
            return None
        return Subscription(
            id=r["id"],
            user_id=r["user_id"],
            plan=Plan(r["plan"]),
            status=SubscriptionStatus(r["status"]),
            provider=BillingProvider(r["provider"]),
            provider_subscription_id=r["provider_subscription_id"],
            current_period_end=r["current_period_end"],
            cancel_at_period_end=r["cancel_at_period_end"],
            trial_end=r["trial_end"],
        )

    async def upsert_subscription(self, sub: Subscription) -> None:
        await self.s.execute(
            text(
                """
            INSERT INTO subscriptions (
                id, user_id, plan, status, provider, provider_subscription_id,
                current_period_end, cancel_at_period_end, trial_end, created_at
            )
            VALUES (:id, :uid, :p, :st, :prov, :psid, :cpe, :cape, :te, now())
            ON CONFLICT (id) DO UPDATE SET
              plan = EXCLUDED.plan,
              status = EXCLUDED.status,
              current_period_end = EXCLUDED.current_period_end,
              cancel_at_period_end = EXCLUDED.cancel_at_period_end,
              trial_end = EXCLUDED.trial_end,
              updated_at = now()
        """
            ),
            {
                "id": str(sub.id),
                "uid": str(sub.user_id),
                "p": sub.plan.value,
                "st": sub.status.value,
                "prov": sub.provider.value,
                "psid": sub.provider_subscription_id,
                "cpe": sub.current_period_end,
                "cape": sub.cancel_at_period_end,
                "te": sub.trial_end,
            },
        )

    async def insert_webhook_event(
        self,
        *,
        event_id: str,
        provider: str,
        payload: dict,
    ) -> bool:
        """Returns True if newly inserted (caller proceeds), False if duplicate."""
        import json

        r = await self.s.execute(
            text(
                """
            INSERT INTO webhook_events (event_id, provider, payload)
            VALUES (:eid, :p, CAST(:pl AS jsonb))
            ON CONFLICT (event_id) DO NOTHING RETURNING 1
        """
            ),
            {"eid": event_id, "p": provider, "pl": json.dumps(payload)},
        )
        return r.first() is not None

    async def list_invoices(
        self,
        *,
        user_id: UUID,
        cursor: str | None,
        limit: int,
    ) -> tuple[list[dict], str | None]:
        params: dict = {"uid": str(user_id), "limit": limit + 1}
        where = "user_id = :uid"
        if cursor:
            params["c"] = cursor
            where += " AND created_at < :c::timestamptz"
        # S608 noqa: `where` is assembled exclusively from literal WHERE
        # fragments authored in this function. All values bound via :params.
        rows = (
            (
                await self.s.execute(
                    text(
                        f"""
            SELECT id, provider, provider_invoice_id, amount_cents, currency,
                   status, paid_at, created_at
              FROM invoices WHERE {where}
             ORDER BY created_at DESC LIMIT :limit
        """
                    ),
                    params,
                )
            )
            .mappings()
            .all()
        )  # noqa: S608
        nxt = None
        if len(rows) > limit:
            rows = rows[:limit]
            nxt = rows[-1]["created_at"].isoformat()
        return [dict(r) for r in rows], nxt
