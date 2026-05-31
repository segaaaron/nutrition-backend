"""Billing bounded context — subscriptions, payments, entitlements.

Gateways: Stripe (US/CA/EU/UK) + Mercado Pago (LatAm). Router selects by
user country with Stripe as the fallback. Webhook events are de-duplicated
by `webhook_events.event_id` UNIQUE.
"""
