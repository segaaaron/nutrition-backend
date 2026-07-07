"""Billing REST endpoints — checkout, subscription, cancel, webhooks, invoices."""

from __future__ import annotations

from datetime import datetime
from urllib.parse import urlparse
from uuid import UUID

from fastapi import APIRouter, Header, Query, Request, status
from pydantic import BaseModel, ConfigDict

from app.billing.domain import BillingProvider, Plan
from app.billing.gateways import MercadoPagoGateway, StripeGateway
from app.billing.repository import SqlBillingRepository
from app.billing.use_cases import (
    CancelSubscription,
    CreateCheckout,
    GetSubscription,
    HandleWebhook,
    StartTrial,
)
from app.core.config import get_settings
from app.core.errors import ValidationError
from app.core.event_bus import get_event_bus
from app.core.logging import get_logger
from app.identity.presentation.dependencies import CurrentUserDep, SessionDep

_log = get_logger("billing.router")

router = APIRouter(tags=["billing"])


class CheckoutResponse(BaseModel):
    checkout_url: str
    session_id: str | None = None
    provider: str | None = None


class TrialResponse(BaseModel):
    id: str
    trial_end: str | None


class SubscriptionResponse(BaseModel):
    id: str | None = None
    plan: str | None = None
    status: str | None = None
    trial_end: str | None = None
    current_period_end: str | None = None
    cancel_at_period_end: bool = False


class CancelResponse(BaseModel):
    id: str
    cancel_at_period_end: bool


class InvoiceOut(BaseModel):
    id: str
    created_at: str
    paid_at: str | None
    amount: float | None = None
    currency: str | None = None
    status: str | None = None


class InvoiceListResponse(BaseModel):
    items: list[InvoiceOut]
    next_cursor: str | None


class WebhookAckResponse(BaseModel):
    received: bool = True


def _allowed_redirect_url(url: str, canonical: str) -> str:
    """Validate that a client-supplied redirect URL shares the same origin
    as the configured canonical URL. Prevents open-redirect attacks.

    Raises ValidationError (422) if the origins do not match or the scheme
    is not https.
    """
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise ValidationError(
            "billing_redirect_url_must_be_https",
            field="success_url",
            supplied=url[:80],
            reason="URL scheme must be https, got: " + (parsed.scheme or "empty"),
        )
    canon = urlparse(canonical)
    if parsed.netloc.lower() != canon.netloc.lower():
        _log.warning(
            "billing.redirect_url_rejected",
            supplied=url[:80],
            allowed_host=canon.netloc,
        )
        raise ValidationError(
            "billing_redirect_url_domain_not_allowed",
            field="success_url",
            supplied=url[:80],
            allowed_host=canon.netloc,
        )
    return url


class CheckoutBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plan: Plan = Plan.PREMIUM
    # Optional client overrides for deep-link routing (e.g. iOS universal
    # links with session-specific query params). Must share the same https
    # origin as the configured BILLING_SUCCESS_URL / BILLING_CANCEL_URL —
    # validated server-side to prevent open-redirect abuse.
    success_url: str | None = None
    cancel_url: str | None = None


@router.post("/billing/checkout", status_code=status.HTTP_200_OK, response_model=CheckoutResponse)
async def checkout(
    body: CheckoutBody,
    current_user: CurrentUserDep,
    session: SessionDep,
) -> CheckoutResponse:
    settings = get_settings()
    success_url = (
        _allowed_redirect_url(body.success_url, settings.billing_success_url)
        if body.success_url
        else settings.billing_success_url
    )
    cancel_url = (
        _allowed_redirect_url(body.cancel_url, settings.billing_cancel_url)
        if body.cancel_url
        else settings.billing_cancel_url
    )
    uc = CreateCheckout(session=session)
    result = await uc(
        user_id=current_user,
        plan=body.plan,
        success_url=success_url,
        cancel_url=cancel_url,
    )
    return CheckoutResponse(**result) if isinstance(result, dict) else result


@router.post("/billing/trial", status_code=status.HTTP_201_CREATED, response_model=TrialResponse)
async def start_trial(current_user: CurrentUserDep, session: SessionDep) -> TrialResponse:
    uc = StartTrial(repo=SqlBillingRepository(session), bus=get_event_bus())
    sub = await uc(user_id=current_user)
    return TrialResponse(
        id=str(sub.id),
        trial_end=sub.trial_end.isoformat() if sub.trial_end else None,
    )


@router.get("/billing/subscription", response_model=SubscriptionResponse)
async def get_subscription(current_user: CurrentUserDep, session: SessionDep) -> SubscriptionResponse:
    uc = GetSubscription(repo=SqlBillingRepository(session))
    result = await uc(current_user)
    return SubscriptionResponse(**result) if isinstance(result, dict) else result


@router.get("/me/subscription", response_model=SubscriptionResponse)
async def get_my_subscription(current_user: CurrentUserDep, session: SessionDep) -> SubscriptionResponse:
    uc = GetSubscription(repo=SqlBillingRepository(session))
    result = await uc(current_user)
    return SubscriptionResponse(**result) if isinstance(result, dict) else result


@router.post("/billing/cancel", response_model=CancelResponse)
async def cancel(current_user: CurrentUserDep, session: SessionDep) -> CancelResponse:
    uc = CancelSubscription(repo=SqlBillingRepository(session), bus=get_event_bus())
    sub = await uc(user_id=current_user)
    return CancelResponse(id=str(sub.id), cancel_at_period_end=sub.cancel_at_period_end)


@router.get("/billing/invoices", response_model=InvoiceListResponse)
async def list_invoices(
    current_user: CurrentUserDep,
    session: SessionDep,
    cursor: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
) -> InvoiceListResponse:
    repo = SqlBillingRepository(session)
    items, nxt = await repo.list_invoices(user_id=current_user, cursor=cursor, limit=limit)
    return InvoiceListResponse(
        items=[
            InvoiceOut(
                **{k: v for k, v in i.items() if k not in ("id", "created_at", "paid_at")},
                id=str(i["id"]),
                created_at=i["created_at"].isoformat(),
                paid_at=i["paid_at"].isoformat() if i["paid_at"] else None,
            )
            for i in items
        ],
        next_cursor=nxt,
    )


# --- Webhooks (provider-signed) ---


@router.post("/webhooks/stripe", response_model=WebhookAckResponse)
async def stripe_webhook(
    request: Request,
    session: SessionDep,
    stripe_signature: str = Header(default="", alias="Stripe-Signature"),
) -> WebhookAckResponse:
    payload = await request.body()
    gw = StripeGateway()
    event = await gw.verify_webhook(payload=payload, signature=stripe_signature)
    uc = HandleWebhook(
        repo=SqlBillingRepository(session),
        bus=get_event_bus(),
        provider=BillingProvider.STRIPE,
    )
    await uc(event=event)
    return WebhookAckResponse()


@router.post("/webhooks/mercadopago", response_model=WebhookAckResponse)
async def mercadopago_webhook(
    request: Request,
    session: SessionDep,
    x_signature: str = Header(default="", alias="X-Signature"),
    x_request_id: str = Header(default="", alias="X-Request-Id"),
) -> WebhookAckResponse:
    payload = await request.body()
    gw = MercadoPagoGateway()
    event = await gw.verify_webhook(
        payload=payload,
        signature=x_signature,
        request_id=x_request_id,
    )
    uc = HandleWebhook(
        repo=SqlBillingRepository(session),
        bus=get_event_bus(),
        provider=BillingProvider.MERCADOPAGO,
    )
    await uc(event=event)
    return WebhookAckResponse()
