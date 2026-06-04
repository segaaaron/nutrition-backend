"""Payment gateway adapters — Stripe + Mercado Pago + router-by-country.

Implemented with `httpx.AsyncClient` directly against the providers' public
REST APIs. We deliberately do NOT depend on the upstream `stripe` /
`mercadopago` Python SDKs because both are synchronous (they call
`requests`), which would block the FastAPI event loop on every billing
operation — a real performance bug under concurrent load.

References:
- Stripe REST API: https://stripe.com/docs/api (form-encoded bodies, Bearer key)
- Stripe webhook signature: https://stripe.com/docs/webhooks/signatures (HMAC-SHA256, ±5 min)
- Stripe Idempotency-Key: https://stripe.com/docs/api/idempotent_requests
- MercadoPago REST: https://www.mercadopago.com/developers/en/reference
- MercadoPago webhook signature: HMAC-SHA256 manifest `id:<id>;request-id:<rid>;ts:<ts>;`
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from decimal import Decimal
from typing import Any
from urllib.parse import urlencode
from uuid import UUID

import httpx

from app.billing.domain import BillingProvider, PaymentGateway, Plan
from app.billing.pricing import price_for
from app.core.config import get_settings
from app.core.errors import UpstreamError

# Stripe-routed regions (ISO-2). Everything else routes to Mercado Pago,
# with Stripe fallback when MP has no presence in that country.
STRIPE_COUNTRIES: frozenset[str] = frozenset(
    {
        "US",
        "CA",
        "GB",
        "DE",
        "FR",
        "ES",
        "IT",
        "PT",
        "NL",
        "BE",
        "AT",
        "CH",
        "IE",
        "PL",
        "SE",
        "NO",
        "DK",
        "FI",
        "AU",
        "NZ",
    }
)
MERCADOPAGO_COUNTRIES: frozenset[str] = frozenset({"AR", "BR", "CL", "CO", "MX", "PE", "UY"})

# Network timeouts: short connect, generous read (gateways occasionally slow).
_HTTP_TIMEOUT = httpx.Timeout(connect=5.0, read=15.0, write=10.0, pool=5.0)

# Webhook replay protection window (seconds). Stripe + MP both use 5 minutes.
_WEBHOOK_WINDOW_S = 300


def _flatten_stripe_params(data: dict[str, Any], prefix: str = "") -> list[tuple[str, str]]:
    """Flatten nested dict/list into Stripe's bracketed form-encoded pairs.

    Example::
        {"line_items": [{"quantity": 1, "price_data": {"currency": "usd"}}]}
        -> [("line_items[0][quantity]", "1"),
            ("line_items[0][price_data][currency]", "usd")]
    """
    out: list[tuple[str, str]] = []
    for key, value in data.items():
        full_key = f"{prefix}[{key}]" if prefix else key
        if isinstance(value, dict):
            out.extend(_flatten_stripe_params(value, full_key))
        elif isinstance(value, list):
            for idx, item in enumerate(value):
                indexed_key = f"{full_key}[{idx}]"
                if isinstance(item, dict):
                    out.extend(_flatten_stripe_params(item, indexed_key))
                else:
                    out.append((indexed_key, str(item)))
        elif isinstance(value, bool):
            out.append((full_key, "true" if value else "false"))
        else:
            out.append((full_key, str(value)))
    return out


class StripeGateway:
    """Stripe gateway — async httpx, no SDK.

    Replaces the synchronous `stripe` Python SDK to avoid blocking the
    event loop. Implements exactly the three operations NOVA needs:
    Checkout Session creation, subscription cancel-at-period-end, and
    webhook signature verification.
    """

    name: BillingProvider = BillingProvider.STRIPE
    _api_base = "https://api.stripe.com/v1"

    def __init__(self) -> None:
        settings = get_settings()
        self._key: str = getattr(settings, "stripe_api_key", "") or ""
        self._webhook_secret: str = getattr(settings, "stripe_webhook_secret", "") or ""

    def _enabled(self) -> bool:
        return bool(self._key)

    async def _post_form(
        self,
        path: str,
        params: dict[str, Any],
        *,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        headers = {
            "Authorization": f"Bearer {self._key}",
            "Content-Type": "application/x-www-form-urlencoded",
        }
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        body = urlencode(_flatten_stripe_params(params))
        url = f"{self._api_base}{path}"
        try:
            async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
                resp = await client.post(url, content=body, headers=headers)
        except httpx.HTTPError as e:
            raise UpstreamError(detail=f"stripe_network_error: {e}") from e
        if resp.status_code >= 400:
            raise UpstreamError(
                detail=f"stripe_http_{resp.status_code}: {resp.text[:200]}"
            )
        try:
            return resp.json()  # type: ignore[no-any-return]
        except ValueError as e:
            raise UpstreamError(detail=f"stripe_invalid_json: {e}") from e

    async def create_checkout(
        self,
        *,
        user_id: UUID,
        email: str,
        plan: Plan,
        country: str,
        success_url: str,
        cancel_url: str,
    ) -> dict:
        cents, currency = price_for(plan, country)
        if not self._enabled():
            # Dev shim — return deterministic dummy URL when API key missing.
            return {
                "provider": self.name.value,
                "url": f"stripe://checkout?user={user_id}&plan={plan.value}",
                "amount_cents": cents,
                "currency": currency,
            }
        params: dict[str, Any] = {
            "mode": "subscription",
            "customer_email": email,
            "line_items": [
                {
                    "price_data": {
                        "currency": currency.lower(),
                        "unit_amount": cents,
                        "recurring": {"interval": "month"},
                        "product_data": {"name": f"NOVA Nutrition – {plan.value}"},
                    },
                    "quantity": 1,
                }
            ],
            "metadata": {"user_id": str(user_id), "plan": plan.value},
            "success_url": success_url,
            "cancel_url": cancel_url,
        }
        # Idempotency: same (user, plan) checkout attempt within 24h dedupes server-side.
        idem = f"checkout:{user_id}:{plan.value}"
        sess = await self._post_form(
            "/checkout/sessions", params, idempotency_key=idem
        )
        url = sess.get("url")
        if not isinstance(url, str):
            raise UpstreamError(detail="stripe_missing_url")
        return {
            "provider": self.name.value,
            "url": url,
            "amount_cents": cents,
            "currency": currency,
        }

    async def cancel_subscription(self, *, provider_sub_id: str) -> None:
        if not self._enabled():
            return
        await self._post_form(
            f"/subscriptions/{provider_sub_id}",
            {"cancel_at_period_end": True},
            idempotency_key=f"cancel:{provider_sub_id}",
        )

    @staticmethod
    def _parse_stripe_sig(signature: str) -> tuple[str, list[str]]:
        ts = ""
        v1_sigs: list[str] = []
        for part in signature.split(","):
            if "=" not in part:
                continue
            k, v = part.split("=", 1)
            k, v = k.strip(), v.strip()
            if k == "t":
                ts = v
            elif k == "v1":
                v1_sigs.append(v)
        return ts, v1_sigs

    async def verify_webhook(self, *, payload: bytes, signature: str) -> dict:
        """Verify Stripe webhook signature (HMAC-SHA256, ±5 min window).

        Replicates `stripe.Webhook.construct_event` using stdlib `hmac`.
        Header format: ``t=<ts>,v1=<sig>[,v1=<sig>...]`` — multiple ``v1``
        entries possible during secret rotation; accept if ANY match.
        """
        if not self._enabled():
            try:
                return json.loads(payload.decode())  # type: ignore[no-any-return]
            except ValueError as e:
                raise UpstreamError(detail=f"stripe_webhook_invalid: {e}") from e
        if not self._webhook_secret:
            raise UpstreamError(detail="stripe_webhook_invalid:secret_not_configured")
        if not signature:
            raise UpstreamError(detail="stripe_webhook_invalid:missing_signature")

        ts, v1_sigs = self._parse_stripe_sig(signature)
        if not ts or not v1_sigs:
            raise UpstreamError(detail="stripe_webhook_invalid:malformed_signature")
        try:
            ts_int = int(ts)
        except ValueError:
            raise UpstreamError(detail="stripe_webhook_invalid:bad_ts") from None
        if abs(time.time() - ts_int) > _WEBHOOK_WINDOW_S:
            raise UpstreamError(detail="stripe_webhook_invalid:stale_ts")

        signed_payload = f"{ts}.".encode() + payload
        expected = hmac.new(
            self._webhook_secret.encode(), signed_payload, hashlib.sha256
        ).hexdigest()
        if not any(hmac.compare_digest(expected, sig) for sig in v1_sigs):
            raise UpstreamError(detail="stripe_webhook_invalid:bad_signature")

        try:
            return json.loads(payload.decode())  # type: ignore[no-any-return]
        except ValueError as e:
            raise UpstreamError(detail=f"stripe_webhook_invalid:bad_payload: {e}") from e


class MercadoPagoGateway:
    """Mercado Pago gateway — async httpx, no SDK.

    Replaces synchronous `mercadopago` Python SDK. Uses the Preapproval
    endpoint for recurring subscriptions and a manually-computed
    HMAC-SHA256 webhook verifier (the SDK does not ship one).
    """

    name: BillingProvider = BillingProvider.MERCADOPAGO
    _api_base = "https://api.mercadopago.com"

    def __init__(self) -> None:
        settings = get_settings()
        self._token: str = (
            getattr(settings, "mercadopago_access_token", "") or ""
        )

    def _enabled(self) -> bool:
        return bool(self._token)

    async def _post_json(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
        }
        url = f"{self._api_base}{path}"
        try:
            async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
                resp = await client.post(url, json=body, headers=headers)
        except httpx.HTTPError as e:
            raise UpstreamError(detail=f"mercadopago_network_error: {e}") from e
        if resp.status_code >= 400:
            raise UpstreamError(
                detail=f"mercadopago_http_{resp.status_code}: {resp.text[:200]}"
            )
        try:
            return resp.json()  # type: ignore[no-any-return]
        except ValueError as e:
            raise UpstreamError(detail=f"mercadopago_invalid_json: {e}") from e

    async def _put_json(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
        }
        url = f"{self._api_base}{path}"
        try:
            async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
                resp = await client.put(url, json=body, headers=headers)
        except httpx.HTTPError as e:
            raise UpstreamError(detail=f"mercadopago_network_error: {e}") from e
        if resp.status_code >= 400:
            raise UpstreamError(
                detail=f"mercadopago_http_{resp.status_code}: {resp.text[:200]}"
            )
        try:
            return resp.json()  # type: ignore[no-any-return]
        except ValueError as e:
            raise UpstreamError(detail=f"mercadopago_invalid_json: {e}") from e

    async def create_checkout(
        self,
        *,
        user_id: UUID,
        email: str,
        plan: Plan,
        country: str,
        success_url: str,
        cancel_url: str,
    ) -> dict:
        cents, currency = price_for(plan, country)
        if not self._enabled():
            return {
                "provider": self.name.value,
                "url": f"mercadopago://checkout?user={user_id}&plan={plan.value}",
                "amount_cents": cents,
                "currency": currency,
            }
        # Decimal-correct unit price (cents → major units, 2 dp); never float math.
        unit_price = float((Decimal(cents) / Decimal(100)).quantize(Decimal("0.01")))
        body: dict[str, Any] = {
            "items": [
                {
                    "title": f"NOVA Nutrition – {plan.value}",
                    "quantity": 1,
                    "currency_id": currency,
                    "unit_price": unit_price,
                }
            ],
            "payer": {"email": email},
            "back_urls": {
                "success": success_url,
                "failure": cancel_url,
                "pending": cancel_url,
            },
            "auto_return": "approved",
            "metadata": {"user_id": str(user_id), "plan": plan.value},
        }
        pref = await self._post_json("/checkout/preferences", body)
        url = pref.get("init_point")
        if not isinstance(url, str):
            raise UpstreamError(detail="mercadopago_missing_init_point")
        return {
            "provider": self.name.value,
            "url": url,
            "amount_cents": cents,
            "currency": currency,
        }

    async def cancel_subscription(self, *, provider_sub_id: str) -> None:
        if not self._enabled():
            return
        await self._put_json(
            f"/preapproval/{provider_sub_id}", {"status": "cancelled"}
        )

    async def verify_webhook(
        self,
        *,
        payload: bytes,
        signature: str,
        request_id: str = "",
    ) -> dict:
        secret = get_settings().mercadopago_webhook_secret
        if not secret:
            raise UpstreamError("mercadopago_webhook_invalid:secret_not_configured")
        if not signature:
            raise UpstreamError("mercadopago_webhook_invalid:missing_signature")

        parts = dict(p.split("=", 1) for p in signature.split(",") if "=" in p)
        ts = parts.get("ts", "")
        v1 = parts.get("v1", "")
        if not ts or not v1:
            raise UpstreamError("mercadopago_webhook_invalid:malformed_signature")

        try:
            ts_int = int(ts)
        except ValueError:
            raise UpstreamError("mercadopago_webhook_invalid:bad_ts") from None
        if abs(time.time() - ts_int) > _WEBHOOK_WINDOW_S:
            raise UpstreamError("mercadopago_webhook_invalid:stale_ts")

        try:
            body = json.loads(payload.decode())
        except Exception as e:
            raise UpstreamError("mercadopago_webhook_invalid:bad_payload") from e

        data_id = str(((body.get("data") or {}).get("id")) or "")
        manifest = f"id:{data_id};request-id:{request_id};ts:{ts};"
        expected = hmac.new(secret.encode(), manifest.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, v1):
            raise UpstreamError("mercadopago_webhook_invalid:bad_signature")

        return body  # type: ignore[no-any-return]


def gateway_for_country(country: str) -> PaymentGateway:
    cu = country.upper()
    if cu in MERCADOPAGO_COUNTRIES:
        return MercadoPagoGateway()
    return StripeGateway()
