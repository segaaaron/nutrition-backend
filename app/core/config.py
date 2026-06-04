"""Application configuration sourced from environment (pydantic-settings).

All env vars are declared in .env.example. Resource limits below are tuned for
the Hostinger KVM 2 baseline (spec §23). Adjust DB_POOL_SIZE etc when scaling
up the VPS.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

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

    # --- Database ---
    database_url: str = "postgresql+asyncpg://nova:novapass@db:5432/nova"
    db_pool_size: int = 15
    db_max_overflow: int = 10
    db_pool_recycle_seconds: int = 3600

    # --- Redis ---
    redis_url: str = "redis://redis:6379/0"
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
    # MASTER feature flag for the hybrid cost cascade. OFF by default in prod
    # until the golden-set calibration validates the 0.7 confidence threshold.
    # When False: every call goes straight to the fallback (gpt-4o full) —
    # behaviour identical to the legacy single-model pipeline.
    # See docs/algorithms/ for golden-set protocol.
    vision_cascade_enabled: bool = False
    # Average confidence threshold to *accept* the primary model output.
    # Below this OR if min(item.confidence) < 0.5 OR items.empty → fallback.
    vision_confidence_threshold: float = 0.7
    # Per-user hourly cap on photo uploads (HTTP 429 on excess).
    vision_photo_uploads_per_hour: int = 30
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
    # Sentry — empty DSN = SDK not initialised (no-op). Conservative sample
    # rates: traces=0.1 keeps perf overhead < 2%, profiles=0.0 disabled
    # until DSN volume budget is known. PII strip enforced in before_send.
    sentry_dsn: str = ""
    sentry_traces_sample_rate: float = 0.1
    sentry_profiles_sample_rate: float = 0.0
    sentry_environment: str = ""  # falls back to `env` when empty
    # --- i18n ---
    supported_locales: str = "en,es,pt,fr,de"
    default_locale: Literal["en", "es", "pt", "fr", "de"] = "en"

    # --- Regions ---
    default_region: Literal["us", "ca", "eu", "uk", "latam"] = "us"

    # --- Billing / Webhooks ---
    stripe_api_key: str = ""
    stripe_webhook_secret: str = ""
    mercadopago_access_token: str = ""
    mercadopago_webhook_secret: str = ""

    # --- CORS ---
    cors_allowed_origins: str = "https://app.nova-nutrition.com"
    ip_rate_limit_per_minute: int = 600

    # --- MVP segment gate ---
    # Refuse onboarding/profile-update for segments where catalog + condition
    # macros are not validated yet. Disable when catalog + condition macro
    # overrides ship (see docs/algorithms/PRE_PROD_AUDIT.md).
    mvp_segment_gate_enabled: bool = True
    # MVP segment gate — current state (2026-06-01):
    #   - lactation: enabled ADR-0016 (200 recipes + LactationGate)
    #   - diabetes_t2: enabled ADR-0018 (974 recipes + DiabetesT2Gate)
    #   - ckd: enabled ADR-0019 (313 recipes with K+P micros + CKDGate)
    #   - pregnancy: enabled ADR-0020 (26,827 pregnancy_safe pool + PregnancyGate
    #     + trimester field in form).
    #   - diabetes_t1: kept blocked — insulin timing/dosing out of scope for
    #     a nutrition tracker; user must use specialised tooling.
    mvp_blocked_conditions: str = "diabetes_t1"
    mvp_blocked_regions: str = "us"

    @property
    def mvp_blocked_conditions_set(self) -> frozenset[str]:
        return frozenset(s.strip() for s in self.mvp_blocked_conditions.split(",") if s.strip())

    @property
    def mvp_blocked_regions_set(self) -> frozenset[str]:
        return frozenset(s.strip() for s in self.mvp_blocked_regions.split(",") if s.strip())

    @property
    def supported_locales_list(self) -> list[str]:
        return [s.strip() for s in self.supported_locales.split(",") if s.strip()]

    @property
    def cors_allowed_origins_list(self) -> list[str]:
        return [s.strip() for s in self.cors_allowed_origins.split(",") if s.strip()]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
