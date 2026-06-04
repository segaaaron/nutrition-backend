"""Billing domain — entities, VO, events, ports."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from app.core.event_bus import DomainEvent


class Plan(StrEnum):
    FREE = "free"
    PREMIUM = "premium"
    FAMILY = "family"


class BillingProvider(StrEnum):
    STRIPE = "stripe"
    MERCADOPAGO = "mercadopago"


class SubscriptionStatus(StrEnum):
    TRIALING = "trialing"
    ACTIVE = "active"
    PAST_DUE = "past_due"
    CANCELLED = "cancelled"
    INCOMPLETE = "incomplete"


@dataclass(slots=True)
class Customer:
    id: UUID
    user_id: UUID
    provider: BillingProvider
    provider_customer_id: str
    country: str
    currency: str


@dataclass(slots=True)
class Subscription:
    id: UUID
    user_id: UUID
    plan: Plan
    status: SubscriptionStatus
    provider: BillingProvider
    provider_subscription_id: str | None
    current_period_end: datetime | None
    cancel_at_period_end: bool
    trial_end: datetime | None


@dataclass(slots=True)
class PaymentMethod:
    id: UUID
    user_id: UUID
    provider: BillingProvider
    provider_pm_id: str
    brand: str | None
    last4: str | None


@dataclass(slots=True)
class Invoice:
    id: UUID
    user_id: UUID
    provider: BillingProvider
    provider_invoice_id: str
    amount_cents: int
    currency: str
    status: str
    paid_at: datetime | None


# --- Events ---


@dataclass(frozen=True, slots=True)
class TrialStarted(DomainEvent):
    user_id: UUID
    plan: str
    trial_end: datetime


@dataclass(frozen=True, slots=True)
class TrialEnded(DomainEvent):
    user_id: UUID
    converted: bool


@dataclass(frozen=True, slots=True)
class SubscriptionCreated(DomainEvent):
    user_id: UUID
    plan: str
    provider: str


@dataclass(frozen=True, slots=True)
class SubscriptionUpdated(DomainEvent):
    user_id: UUID
    plan: str
    status: str


@dataclass(frozen=True, slots=True)
class SubscriptionCancelled(DomainEvent):
    user_id: UUID
    at: datetime


@dataclass(frozen=True, slots=True)
class PaymentSucceeded(DomainEvent):
    user_id: UUID
    amount_cents: int
    currency: str


@dataclass(frozen=True, slots=True)
class PaymentFailed(DomainEvent):
    user_id: UUID
    amount_cents: int
    currency: str
    reason: str


# --- Ports ---


class PaymentGateway(Protocol):
    name: BillingProvider

    async def create_checkout(
        self,
        *,
        user_id: UUID,
        email: str,
        plan: Plan,
        country: str,
        success_url: str,
        cancel_url: str,
    ) -> dict: ...

    async def cancel_subscription(self, *, provider_sub_id: str) -> None: ...

    async def verify_webhook(self, *, payload: bytes, signature: str) -> dict: ...
