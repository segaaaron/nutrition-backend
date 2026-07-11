"""Application configuration sourced from environment (pydantic-settings).

All env vars are declared in .env.example. Resource limits below are tuned for
the Hostinger KVM 2 baseline (spec §23). Adjust DB_POOL_SIZE etc when scaling
up the VPS.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Runtime ---
    env: Literal["dev", "staging", "prod"] = "dev"
    log_level: str = "INFO"
    app_name: str = "nova-nutrition-backend"
    app_version: str = "0.1.0"
    # Process role. Drives which prod validations are HTTP-only and therefore
    # irrelevant to the arq worker (CORS_ALLOWED_ORIGINS, billing redirect
    # URLs). Default "api" preserves the strict posture for the HTTP service;
    # worker compose sets SERVICE_ROLE=worker so its boot does not require
    # HTTP-layer env vars that it never reads. Avoids a shared-Settings crash
    # loop when the panel forgets to mirror HTTP vars onto the worker.
    service_role: Literal["api", "worker"] = "api"

    # --- Database ---
    # REQUIRED — no default. A silent fallback masked a Dokploy env-propagation
    # bug in prod (container booted with hardcoded `nova:novapass@db:5432/nova`
    # while the managed DB expected `postgres@…`). Pydantic now fails loud at
    # boot if DATABASE_URL is missing or wrong driver.
    database_url: str
    db_pool_size: int = 8
    db_max_overflow: int = 5
    db_pool_recycle_seconds: int = 3600

    # --- Redis ---
    # REQUIRED — no fallback default. Same rationale as DATABASE_URL: a silent
    # `redis://redis:6379/0` default masked Dokploy env-propagation failures
    # (container booted talking to a non-existent `redis` hostname). Fail loud
    # at boot via validator instead.
    redis_url: str
    redis_max_connections: int = 50
    redis_socket_keepalive: bool = True

    # --- Auth ---
    jwt_private_key_path: str = "/secrets/jwt.pem"
    jwt_public_key_path: str = "/secrets/jwt.pub"
    jwt_access_ttl_seconds: int = 900
    jwt_refresh_ttl_seconds: int = 2_592_000
    jwt_issuer: str = "nova-nutrition"
    jwt_audience: str = "nova-mobile"

    # --- JWT key rotation (ASVS V2 / S0-J) ---
    # Comma-separated entries: "kid:path_to_priv.pem,kid2:path_to_priv2.pem"
    # Public key assumed at path.replace('.pem', '.pub')
    # If empty, falls back to jwt_private_key_path + jwt_public_key_path (legacy).
    jwt_signing_keys: str = ""
    jwt_active_kid: str = "key_v1"
    # Comma-separated kids to reject immediately (compromised keys)
    jwt_revoked_kids: str = ""

    # --- OAuth ---
    google_oauth_client_id: str = ""
    apple_oauth_client_id: str = ""
    apple_oauth_team_id: str = ""
    apple_oauth_key_id: str = ""

    # --- OpenAI ---
    openai_api_key: str = ""
    # Legacy single-model knob (kept for backward compat — if cascade vars
    # are empty / equal, behaviour reduces to "always gpt-4o full").
    openai_vision_model: str = "gpt-4o-2024-08-06"
    openai_chat_model: str = "gpt-4o-mini"
    openai_embed_model: str = "text-embedding-3-large"
    openai_embed_dim: int = 1536

    # --- Vision cost-cascade (hybrid pipeline, target -75-80% cost) ---
    # Primary cheap model attempted first; on low confidence we fall back to
    # the heavier, more accurate model. Set both equal to disable cascade.
    openai_vision_model_primary: str = "gpt-4o-mini"
    openai_vision_model_fallback: str = "gpt-4o-2024-08-06"
    # MASTER feature flag for the hybrid cost cascade. ON by default since
    # 2026-06-11 (owner decision): the DB macro grounding in
    # process_vision_job compensates the cheap model's weak kcal
    # arithmetic, so the historical reason to keep this OFF (pending
    # golden-set calibration) no longer outweighs the ~65% cost saving.
    # When False: every call goes straight to the fallback (gpt-4o full) —
    # behaviour identical to the legacy single-model pipeline.
    # See docs/algorithms/ for golden-set protocol.
    vision_cascade_enabled: bool = True
    # Average confidence threshold to *accept* the primary model output.
    # Below this OR if min(item.confidence) < 0.5 OR items.empty → fallback.
    vision_confidence_threshold: float = 0.7
    # Per-user daily cap on photo uploads (HTTP 429 on excess).
    # 10/day covers breakfast+lunch+dinner+snack+retries for 99% of users.
    # Renamed from vision_photo_uploads_per_hour — old env var is ignored by pydantic.
    vision_photo_uploads_per_day: int = 10
    # Backward-compat alias: if old hourly var is set in .env, it is read here
    # and checked at startup (see app/core/startup.py or similar) to warn operator.
    vision_photo_uploads_per_hour: int = 0  # 0 = not set; >0 = operator using old var
    # SHA256 dedup window. Re-uses a previous completed job's items when the
    # same compressed image is submitted by ANY user within the TTL.
    vision_cache_ttl_days: int = 90
    # Hard cap on completion tokens for vision calls. Bumped 400 -> 1200 to
    # avoid JSON truncation on dense buffet plates (HIGH-3 fix). At
    # gpt-4o-mini output pricing (~$0.66/1M), ceiling per call is ~$0.0008.
    vision_max_output_tokens: int = 1200
    # Pixel threshold (width AND height) — under this → detail="low" (85 tok
    # image cost), otherwise detail="high" (765 tok). OpenAI vision formula.
    vision_low_detail_max_dim: int = 500
    # --- Vision food pre-filter (cheap classifier before main cascade) ---
    # Rejects non-food images (supplements, water, pills, objects) BEFORE the
    # expensive vision call to save ~$0.005/photo on bad uploads. The filter
    # itself costs ~$0.0001/photo (gpt-4o-mini, detail:low, ~30 out tokens).
    # Default ON — fail-open on errors (lets through if uncertain or upstream
    # failure).
    vision_food_prefilter_enabled: bool = True

    # --- Cost cap (ADR-0004) ---
    cost_cap_usd_per_user_per_day: float = 1.50
    cost_cap_usd_per_org_per_day: float = 500.00
    cost_cap_alarm_pct: float = 0.80

    # --- Rate limits ---
    rate_limit_auth_per_min: int = 10
    rate_limit_ai_per_min: int = 5
    rate_limit_api_per_min: int = 60

    # --- Arq worker (Hostinger sizing — pyvips peak ~750 MB/job) ---
    arq_max_jobs: int = 2
    arq_job_timeout_seconds: int = 180
    arq_keep_result_seconds: int = 3600
    arq_max_queue_depth: int = 100

    # --- Web concurrency ---
    web_concurrency: int = 2
    web_max_concurrent_requests: int = 200

    # --- Observability ---
    # Local error tracker writes rotated JSONL to this path. Override per env.
    nova_error_log_path: str = "/var/log/nova/errors.jsonl"
    # --- i18n ---
    # NOTE: The authoritative gate is app/shared/i18n/locale_resolver.Locale
    # (currently Literal["es", "en"]). These config strings are advisory; any
    # tag not present in `Locale` falls back to default at resolve-time.
    supported_locales: str = "en,es"
    default_locale: Literal["en", "es"] = "en"

    # --- Regions ---
    default_region: Literal["us", "ca", "latam"] = "us"

    # --- Billing / Webhooks ---
    stripe_api_key: str = ""
    stripe_webhook_secret: str = ""
    mercadopago_access_token: str = ""
    mercadopago_webhook_secret: str = ""
    # Stripe redirect URLs post-checkout / on-cancel. REQUIRED when
    # service_role=api (validated below); worker never reads these.
    billing_success_url: str = ""
    billing_cancel_url: str = ""

    # --- Email (Resend — https://resend.com/) ---
    # Master kill-switch. When False, all email sends become no-ops (logged
    # but never dispatched). Default OFF for closed-beta safety.
    email_enabled: bool = False
    # Resend REST API key. Empty = no-op (NullEmailSender). Required when
    # email_enabled=true (validated in factory — fail-loud at startup).
    resend_api_key: str = ""

    # --- CORS ---
    # Default = "" (deny-all). Owner MUST set explicitly per env (Dokploy panel
    # or .env). Hardcoded hostname removed 2026-06-04 — fail-closed posture.
    cors_allowed_origins: str = ""
    ip_rate_limit_per_minute: int = 600

    @model_validator(mode="after")
    def _validate_prod_requirements(self) -> Settings:
        is_api = self.service_role == "api"
        is_prod_api = is_api and self.env == "prod"
        # CORS gate: prod-api only (preserves original env=="prod" rule).
        if is_prod_api and not self.cors_allowed_origins.strip():
            raise ValueError(
                "CORS_ALLOWED_ORIGINS is REQUIRED in prod (api) — no fallback. "
                "Set it in the Dokploy panel (e.g. 'https://app.nova.com')."
            )
        # Billing gates: all envs when api (preserves original always-required
        # field_validator rule). Worker skips since it never invokes Stripe.
        if is_api and not self.billing_success_url.strip():
            raise ValueError(
                "BILLING_SUCCESS_URL is REQUIRED (api) — no fallback default."
            )
        if is_api and not self.billing_cancel_url.strip():
            raise ValueError(
                "BILLING_CANCEL_URL is REQUIRED (api) — no fallback default."
            )
        if self.billing_success_url and not self.billing_success_url.startswith("https://"):
            raise ValueError(
                f"BILLING_SUCCESS_URL must use https://; got '{self.billing_success_url[:40]}…'."
            )
        if self.billing_cancel_url and not self.billing_cancel_url.startswith("https://"):
            raise ValueError(
                f"BILLING_CANCEL_URL must use https://; got '{self.billing_cancel_url[:40]}…'."
            )
        if self.email_enabled and not self.resend_api_key.strip():
            raise ValueError(
                "RESEND_API_KEY is REQUIRED when EMAIL_ENABLED=true. "
                "Set it in the Dokploy panel or .env."
            )
        return self

    @field_validator("database_url")
    @classmethod
    def _validate_database_url(cls, v: str) -> str:
        """Fail loud on missing or wrong-driver DATABASE_URL.

        The hardcoded default removed on 2026-06-04 caused a silent fallback
        in prod when the Dokploy panel env var failed to propagate to the
        container. The app booted with `nova:novapass@db:5432/nova` and then
        died at first query with `password authentication failed for user
        "nova"`. With this validator the error surfaces at boot instead.
        """
        if not v:
            raise ValueError(
                "DATABASE_URL env var is REQUIRED — no fallback default. "
                "Set it in the Dokploy panel (or .env for local dev)."
            )
        if not v.startswith("postgresql+asyncpg://"):
            scheme = v.split("://", 1)[0] if "://" in v else "<no-scheme>"
            raise ValueError(
                f"DATABASE_URL must use the asyncpg driver "
                f"('postgresql+asyncpg://…'); got scheme '{scheme}://'."
            )
        return v

    @field_validator("redis_url")
    @classmethod
    def _validate_redis_url(cls, v: str) -> str:
        """Fail loud on missing or wrong-scheme REDIS_URL.

        Hardcoded `redis://redis:6379/0` default removed on 2026-06-04 — same
        rationale as DATABASE_URL: silent fallback hid Dokploy env propagation
        failures (boot succeeded against a phantom `redis` hostname, every
        Redis call then 500'd at runtime).
        """
        if not v:
            raise ValueError(
                "REDIS_URL env var is REQUIRED — no fallback default. "
                "Set it in the Dokploy panel (or .env for local dev)."
            )
        if not (v.startswith("redis://") or v.startswith("rediss://")):
            scheme = v.split("://", 1)[0] if "://" in v else "<no-scheme>"
            raise ValueError(
                f"REDIS_URL must use redis:// or rediss:// scheme; "
                f"got '{scheme}://'."
            )
        return v

    @property
    def supported_locales_list(self) -> list[str]:
        return [s.strip() for s in self.supported_locales.split(",") if s.strip()]

    @property
    def cors_allowed_origins_list(self) -> list[str]:
        return [s.strip() for s in self.cors_allowed_origins.split(",") if s.strip()]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
