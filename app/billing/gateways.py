"""Payment gateway adapters — Stripe + Mercado Pago + router-by-country.

Implementations are deliberately thin: real SDK calls are wrapped behind the
PaymentGateway Protocol so unit tests can swap in fakes. The SDKs (`stripe`,
`mercadopago`) are optional at import time — production deploys must add them
to the lock file before going live.
"""
from __future__ import annotations

from uuid import UUID

from app.billing.domain import BillingProvider, PaymentGateway, Plan
from app.billing.pricing import currency_for, price_for
from app.core.config import get_settings
from app.core.errors import UpstreamError

# Stripe-routed regions (ISO-2). Everything else routes to Mercado Pago,
# with Stripe fallback when MP has no presence in that country.
STRIPE_COUNTRIES: frozenset[str] = frozenset(
    {"US", "CA", "GB", "DE", "FR", "ES", "IT", "PT", "NL", "BE", "AT", "CH",
     "IE", "PL", "SE", "NO", "DK", "FI", "AU", "NZ"}
)
MERCADOPAGO_COUNTRIES: frozenset[str] = frozenset(
    {"AR", "BR", "CL", "CO", "MX", "PE", "UY"}
)


class StripeGateway:
    name: BillingProvider = BillingProvider.STRIPE

    def __init__(self) -> None:
        self._key = get_settings().__dict__.get("stripe_api_key", "")
        try:
            import stripe  # type: ignore
            stripe.api_key = self._key
            self._stripe = stripe
        except Exception:  # noqa: BLE001
            self._stripe = None

    async def create_checkout(
        self, *, user_id: UUID, email: str, plan: Plan,
        country: str, success_url: str, cancel_url: str,
    ) -> dict:
        cents, currency = price_for(plan, country)
        if self._stripe is None:
            # Dev shim — return a deterministic dummy URL when SDK missing.
            return {
                "provider": self.name.value,
                "url": f"stripe://checkout?user={user_id}&plan={plan.value}",
                "amount_cents": cents, "currency": currency,
            }
        sess = self._stripe.checkout.Session.create(  # type: ignore[attr-defined]
            mode="subscription",
            customer_email=email,
            line_items=[{
                "price_data": {
                    "currency": currency.lower(),
                    "unit_amount": cents,
                    "recurring": {"interval": "month"},
                    "product_data": {"name": f"NOVA Nutrition – {plan.value}"},
                },
                "quantity": 1,
            }],
            metadata={"user_id": str(user_id), "plan": plan.value},
            success_url=success_url, cancel_url=cancel_url,
        )
        return {
            "provider": self.name.value, "url": sess.url,
            "amount_cents": cents, "currency": currency,
        }

    async def cancel_subscription(self, *, provider_sub_id: str) -> None:
        if self._stripe is None:
            return
        self._stripe.Subscription.modify(  # type: ignore[attr-defined]
            provider_sub_id, cancel_at_period_end=True,
        )

    async def verify_webhook(self, *, payload: bytes, signature: str) -> dict:
        if self._stripe is None:
            import json
            return json.loads(payload.decode())
        secret = get_settings().__dict__.get("stripe_webhook_secret", "")
        try:
            evt = self._stripe.Webhook.construct_event(  # type: ignore[attr-defined]
                payload, signature, secret,
            )
            return evt
        except Exception as e:  # noqa: BLE001
            raise UpstreamError(detail=f"stripe_webhook_invalid: {e}") from e


class MercadoPagoGateway:
    name: BillingProvider = BillingProvider.MERCADOPAGO

    def __init__(self) -> None:
        self._token = get_settings().__dict__.get("mercadopago_access_token", "")
        try:
            import mercadopago  # type: ignore
            self._mp = mercadopago.SDK(self._token) if self._token else None
        except Exception:  # noqa: BLE001
            self._mp = None

    async def create_checkout(
        self, *, user_id: UUID, email: str, plan: Plan,
        country: str, success_url: str, cancel_url: str,
    ) -> dict:
        cents, currency = price_for(plan, country)
        if self._mp is None:
            return {
                "provider": self.name.value,
                "url": f"mercadopago://checkout?user={user_id}&plan={plan.value}",
                "amount_cents": cents, "currency": currency,
            }
        pref = self._mp.preference().create({  # type: ignore[attr-defined]
            "items": [{
                "title": f"NOVA Nutrition – {plan.value}",
                "quantity": 1,
                "currency_id": currency,
                "unit_price": cents / 100.0,
            }],
            "payer": {"email": email},
            "back_urls": {"success": success_url, "failure": cancel_url, "pending": cancel_url},
            "auto_return": "approved",
            "metadata": {"user_id": str(user_id), "plan": plan.value},
        })
        return {
            "provider": self.name.value,
            "url": pref["response"]["init_point"],
            "amount_cents": cents, "currency": currency,
        }

    async def cancel_subscription(self, *, provider_sub_id: str) -> None:
        if self._mp is None:
            return
        self._mp.preapproval().update(provider_sub_id, {"status": "cancelled"})  # type: ignore[attr-defined]

    async def verify_webhook(self, *, payload: bytes, signature: str) -> dict:
        # Mercado Pago uses a signed query parameter (x-signature). For Sprint
        # 8 we capture the raw payload and rely on IP allowlist at the edge
        # (Cloudflare) for the first cut; HMAC validation is added in a
        # follow-up alongside the production webhook URL.
        import json
        return json.loads(payload.decode())


def gateway_for_country(country: str) -> PaymentGateway:
    cu = country.upper()
    if cu in MERCADOPAGO_COUNTRIES:
        return MercadoPagoGateway()
    return StripeGateway()
