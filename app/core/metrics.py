"""Cross-cutting Prometheus metric definitions.

Centralised so importing modules don't accidentally re-declare a counter
under the same name (which raises in prometheus_client). Individual
bounded contexts may import these and increment from their own code.
"""
from __future__ import annotations

import time

from fastapi import Request
from prometheus_client import Counter, Gauge, Histogram
from starlette.middleware.base import BaseHTTPMiddleware

# --- HTTP ---
HTTP_DURATION = Histogram(
    "http_request_duration_seconds",
    "HTTP request duration in seconds",
    ["method", "path", "status"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)

# --- Vision / coach (referenced now, populated as those contexts land) ---
VISION_JOB_DURATION = Histogram(
    "vision_job_duration_seconds",
    "End-to-end vision IA job wall-clock duration",
    buckets=(0.5, 1.0, 2.5, 5.0, 10.0, 20.0, 40.0, 80.0),
)

# --- Arq ---
ARQ_QUEUE_DEPTH = Gauge(
    "arq_queue_depth",
    "Current Arq queue depth (pending jobs in Redis)",
)
ARQ_JOB_FAILURES = Counter(
    "arq_job_failures_total",
    "Total failed Arq jobs",
    ["task_name"],
)

# --- Domain signals ---
RECALIBRATION_TRIGGERED = Counter(
    "recalibration_triggered_total",
    "Times ADR-0002 metabolic recalibration fired",
)
AUTH_REFRESH_FAMILY_REVOKED = Counter(
    "auth_refresh_family_revoked_total",
    "Refresh-token families revoked because of detected reuse",
)
PLAN_GENERATION_LLM_SWAP_ACCEPTANCE = Counter(
    "plan_generation_llm_swap_acceptance_total",
    "Layer-4 LLM swaps accepted after post-validation",
)
ALLERGEN_EXCLUSION_APPLIED = Counter(
    "allergen_exclusion_applied_total",
    "Times the Layer-1 allergen hard exclude filtered out at least one recipe",
)
CATALOG_INGEST_REJECTED = Counter(
    "catalog_ingest_rejected_total",
    "Catalog ingest rows rejected per gate",
    ["gate"],
)


class HttpMetricsMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        start = time.perf_counter()
        response = await call_next(request)
        elapsed = time.perf_counter() - start
        # Use the matched route template (path) when available so the metric
        # cardinality stays bounded — never use the raw URL.
        route = request.scope.get("route")
        path = getattr(route, "path", None) or request.url.path
        HTTP_DURATION.labels(
            method=request.method, path=path, status=str(response.status_code),
        ).observe(elapsed)
        return response


async def get_arq_queue_depth(redis) -> int:
    """LLEN of the default Arq queue. Defensive: returns 0 on any error."""
    try:
        return int(await redis.llen("arq:queue"))
    except Exception:  # noqa: BLE001
        return 0
