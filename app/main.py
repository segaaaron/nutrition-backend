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
from app.core.redis import close_redis, get_redis
from app.identity.presentation.router import router as identity_router
from app.profile.presentation.router import router as profile_router


class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        rid = request.headers.get("x-request-id") or str(uuid.uuid4())
        request.state.request_id = rid
        response = await call_next(request)
        response.headers["x-request-id"] = rid
        return response


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)
    log = get_logger("app.main")

    app = FastAPI(
        title="NOVA Nutrition API",
        version=settings.app_version,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allowed_origins_list,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["*"],
        expose_headers=["x-request-id"],
    )
    app.add_middleware(GZipMiddleware, minimum_size=512)
    app.add_middleware(RequestIdMiddleware)

    register_exception_handlers(app)

    # --- Bounded-context routers ---
    app.include_router(identity_router)
    app.include_router(profile_router)

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
