"""Application configuration sourced from environment (pydantic-settings).

All env vars are declared in .env.example. Resource limits below are tuned for
the Hostinger KVM 2 baseline (spec §23). Adjust DB_POOL_SIZE etc when scaling
up the VPS.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field
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
    openai_vision_model: str = "gpt-4o-2024-08-06"
    openai_chat_model: str = "gpt-4o-mini"
    openai_stt_model: str = "whisper-1"
    openai_embed_model: str = "text-embedding-3-large"
    openai_embed_dim: int = 1536

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

    # --- MVP segment gate (handoff 2026-06-01) ---
    # Refuse onboarding/profile-update for segments where catalog + algorithms
    # are not clinically safe yet. Disable when catalog + condition macro
    # overrides ship (see docs/algorithms/PRE_PROD_AUDIT.md).
    mvp_segment_gate_enabled: bool = True
    # MVP segment gate — final state after H2 lifts (2026-06-01):
    #   - lactation: lifted ADR-0016 (200 recipes + LactationGate)
    #   - diabetes_t2: lifted ADR-0018 (974 recipes + DiabetesT2Gate)
    #   - ckd: lifted ADR-0019 (313 recipes with K+P micros + CKDGate)
    #   - pregnancy: lifted ADR-0020 (26,827 pregnancy_safe pool + PregnancyGate
    #     + trimester field in form). Per scope clarification: NOVA is a
    #     nutrition planner, not clinical advice; disclaimer-covered.
    #   - diabetes_t1: kept blocked — insulin timing/dosing requires explicit
    #     clinical management beyond current algorithm scope.
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
