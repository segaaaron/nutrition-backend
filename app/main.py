"""FastAPI application factory.

Routers are registered by each bounded context's presentation layer once their
endpoints land. Today the factory only wires cross-cutting middleware,
exception handlers, health checks and metrics.
"""
from __future__ import annotations

import uuid

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.config import get_settings
from app.core.db import dispose_engine, get_engine
from app.core.errors import register_exception_handlers
from app.core.logging import configure_logging, get_logger
from app.core.anti_sniff import AntiSniffMiddleware
from app.core.ip_rate_limit import IpRateLimitMiddleware
from app.core.security_headers import SecurityHeadersMiddleware
from app.core.sentry import init_sentry
from app.core.metrics import ARQ_QUEUE_DEPTH, HttpMetricsMiddleware, get_arq_queue_depth
from app.core.redis import close_redis, get_redis
from app.coach.presentation.router import router as coach_router
from app.identity.presentation.router import router as identity_router
from app.notifications.presentation.router import router as notifications_router
from app.nutrition.presentation.router import router as nutrition_router
from app.profile.presentation.router import router as profile_router
from app.plan.presentation.router import router as plan_router
from app.recipes.presentation.router import router as recipes_router
from app.tracking.presentation.fasting_router import router as fasting_router
from app.tracking.presentation.food_log_router import router as food_log_router
from app.tracking.presentation.goals_today import router as goals_today_router
from app.tracking.presentation.progress_router import router as progress_router
from app.tracking.presentation.router import router as tracking_router
from app.grocery.router import router as grocery_router
from app.gamification.presentation.router import router as gamification_router
from app.billing.router import router as billing_router
from app.vision.presentation.router import router as vision_router
from app.voice.presentation.router import router as voice_router


class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        rid = request.headers.get("x-request-id") or str(uuid.uuid4())
        request.state.request_id = rid
        response = await call_next(request)
        response.headers["x-request-id"] = rid
        return response




def create_app() -> FastAPI:
    init_sentry()
    settings = get_settings()
    configure_logging(settings.log_level)
    log = get_logger("app.main")

    is_prod = settings.env == "prod"
    # OWASP API9 — disable interactive docs + raw OpenAPI in production.
    app = FastAPI(
        title="NOVA Nutrition API",
        version=settings.app_version,
        docs_url=None if is_prod else "/docs",
        redoc_url=None if is_prod else "/redoc",
        openapi_url=None if is_prod else "/openapi.json",
    )

    # CORS — explicit origins only. allow_headers narrowed (was '*').
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allowed_origins_list,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=[
            "Authorization", "Content-Type", "Idempotency-Key",
            "x-request-id", "x-signature",
        ],
        expose_headers=["x-request-id"],
        max_age=600,
    )
    app.add_middleware(SecurityHeadersMiddleware, is_production=is_prod)
    app.add_middleware(AntiSniffMiddleware, enforce=is_prod)
    app.add_middleware(IpRateLimitMiddleware, limit_per_minute=settings.ip_rate_limit_per_minute)
    app.add_middleware(GZipMiddleware, minimum_size=512)
    app.add_middleware(RequestIdMiddleware)
    app.add_middleware(HttpMetricsMiddleware)

    register_exception_handlers(app)

    # --- Bounded-context routers ---
    app.include_router(identity_router)
    app.include_router(profile_router)
    app.include_router(nutrition_router)
    app.include_router(recipes_router)
    app.include_router(plan_router)
    app.include_router(tracking_router)
    app.include_router(food_log_router)
    app.include_router(fasting_router)
    app.include_router(progress_router)
    app.include_router(grocery_router)
    app.include_router(gamification_router)
    app.include_router(goals_today_router)
    app.include_router(vision_router)
    app.include_router(voice_router)
    app.include_router(coach_router)
    app.include_router(notifications_router)
    app.include_router(billing_router)

    # --- Domain event subscriptions ---
    from app.core.event_bus import get_event_bus
    from app.coach.application.event_handlers import register as register_coach_handlers
    from app.gamification.application.event_handlers import register as register_gamification_handlers
    from app.nutrition.event_handlers import register as register_nutrition_handlers
    from app.tracking.event_handlers import register as register_tracking_handlers
    bus = get_event_bus()
    register_nutrition_handlers(bus)
    register_coach_handlers(bus)
    register_gamification_handlers(bus)
    register_tracking_handlers(bus)

    @app.get("/healthz", tags=["ops"])
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/readyz", tags=["ops"])
    async def readyz() -> JSONResponse:
        checks: dict[str, str] = {}
        try:
            engine = get_engine()
            async with engine.connect() as conn:
                await conn.exec_driver_sql("SELECT 1")
            checks["db"] = "ok"
        except Exception as exc:  # noqa: BLE001
            checks["db"] = f"down: {exc!s}"

        try:
            await get_redis().ping()
            checks["redis"] = "ok"
        except Exception as exc:  # noqa: BLE001
            checks["redis"] = f"down: {exc!s}"

        try:
            depth = await get_arq_queue_depth(get_redis())
            ARQ_QUEUE_DEPTH.set(depth)
            cap = settings.arq_max_queue_depth
            checks["arq_queue"] = "ok" if depth < cap else f"backpressure: depth={depth}>={cap}"
        except Exception as exc:  # noqa: BLE001
            checks["arq_queue"] = f"down: {exc!s}"

        ok = all(v == "ok" for v in checks.values())
        return JSONResponse(status_code=200 if ok else 503, content=checks)

    @app.get("/metrics", tags=["ops"], include_in_schema=False)
    async def metrics() -> PlainTextResponse:
        return PlainTextResponse(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    @app.on_event("startup")
    async def _startup() -> None:
        log.info("app.startup", env=settings.env, version=settings.app_version)

    @app.on_event("shutdown")
    async def _shutdown() -> None:
        await dispose_engine()
        await close_redis()
        log.info("app.shutdown")

    return app


app = create_app()
