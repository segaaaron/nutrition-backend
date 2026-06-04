"""Cross-cutting Prometheus metric definitions.

Centralised so importing modules don't accidentally re-declare a counter
under the same name (which raises in prometheus_client). Individual
bounded contexts may import these and increment from their own code.
"""

from __future__ import annotations

import time

from fastapi import Request
from prometheus_client import Counter, Gauge, Histogram
from redis.asyncio import Redis
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

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

# --- Vision cost-cascade (SHA dedup + mini→full fallback) ---
VISION_CACHE_HITS = Counter(
    "vision_cache_hits_total",
    "Vision jobs short-circuited by SHA256 dedup cache (no provider call)",
)
VISION_CACHE_MISSES = Counter(
    "vision_cache_misses_total",
    "Vision jobs that missed the SHA256 cache and called the provider",
)
VISION_FALLBACK = Counter(
    "vision_fallback_total",
    "Times the cascade escalated from the primary (mini) to the full model",
    ["reason"],
)
VISION_PRIMARY_OK = Counter(
    "vision_primary_ok_total",
    "Times the primary (mini) model output was accepted without fallback",
)
VISION_DETAIL_LEVEL = Counter(
    "vision_detail_level_total",
    "Distribution of the auto-selected image detail level",
    ["detail"],
)
VISION_PARSE_ERRORS = Counter(
    "vision_parse_errors_total",
    "Times the OpenAI response failed to JSON-decode (truncation, malformed)",
    ["model"],
)
VISION_INFLIGHT_LOCK_WAITS = Counter(
    "vision_inflight_lock_waits_total",
    "Times a worker waited on another worker's in-flight SHA lock",
    ["outcome"],  # outcome: hit, timeout
)
VISION_PREFILTER_TOTAL = Counter(
    "vision_prefilter_total",
    "Pre-filter classification result (accept/reject)",
    ["result", "reason"],
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
CATALOG_NULL_RATIO = Gauge(
    "catalog_null_ratio",
    "Ratio of recipe rows where the named column is NULL. Driven by "
    "scripts/catalog_completeness_audit.py — see docs/ops/CATALOG_AUDIT.md. "
    "R6 fail-closed (2026-06-03): NULL safety-critical columns exclude rows from "
    "Layer 1 candidate sets, so a rising ratio shrinks the catalogue.",
    ["column"],
)


class HttpMetricsMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        start = time.perf_counter()
        response = await call_next(request)
        elapsed = time.perf_counter() - start
        # Use the matched route template (path) when available so the metric
        # cardinality stays bounded — never use the raw URL.
        route = request.scope.get("route")
        path = getattr(route, "path", None) or request.url.path
        HTTP_DURATION.labels(
            method=request.method,
            path=path,
            status=str(response.status_code),
        ).observe(elapsed)
        return response


async def get_arq_queue_depth(redis: Redis) -> int:
    """LLEN of the default Arq queue. Defensive: returns 0 on any error."""
    try:
        result = await redis.llen("arq:queue")  # type: ignore[misc]
        return int(result)
    except Exception:  # noqa: BLE001
        return 0
