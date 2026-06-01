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
    sentry_dsn: str = ""
    sentry_environment: str = "production"
    sentry_traces_sample_rate: float = 0.10
    sentry_profiles_sample_rate: float = 0.0
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

    @property
    def supported_locales_list(self) -> list[str]:
        return [s.strip() for s in self.supported_locales.split(",") if s.strip()]

    @property
    def cors_allowed_origins_list(self) -> list[str]:
        return [s.strip() for s in self.cors_allowed_origins.split(",") if s.strip()]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
