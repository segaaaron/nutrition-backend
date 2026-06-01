# MercadoPago Webhook Setup

Set `MERCADOPAGO_WEBHOOK_SECRET` in production env. Retrieve from
MercadoPago dashboard → Webhooks → Secret. Rotate every 90 days.

Replay window: 5 minutes (signatures older than 5 min rejected).
HMAC algorithm: SHA-256 over manifest `id:<data_id>;request-id:<x-request-id>;ts:<ts>;`.
