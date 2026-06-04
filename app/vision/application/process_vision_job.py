"""Worker use case — runs the vision pipeline for one VisionJob.

Steps:
  1. Mark job running.
  2. Try SHA dedup cache (cross-user, PII-stripped).
  3. Otherwise acquire Redis inflight lock + call VisionProvider.
  4. For each item: FoodMatcher.match — ALWAYS per-user, even on cache hit.
  5. Insert one food_logs row per matched item (or per item if free_text fallback).
  6. Mark job completed with persisted detected_items.
  7. Publish FoodPhotoLogged (coach + gamification subscribers).
  8. Notify client via Redis pubsub.

On any failure: mark_failed + publish VisionJobFailed + push to job_deadletter.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Literal
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.event_bus import EventBus
from app.core.logging import get_logger
from app.core.metrics import (
    VISION_CACHE_HITS,
    VISION_CACHE_MISSES,
    VISION_INFLIGHT_LOCK_WAITS,
    VISION_JOB_DURATION,
)
from app.core.redis import get_redis
from app.vision.domain.entities import DetectedFoodItem
from app.vision.domain.events import FoodPhotoLogged, VisionJobCompleted, VisionJobFailed
from app.vision.domain.ports import FoodMatcher, JobNotifier, VisionJobRepository, VisionProvider

log = get_logger("vision.process")

# LOW fix: confidence floor for auto-insert into food_logs. Items below
# this AND without a catalog match stay in detected_items JSONB for user
# review. Threshold is calibrated against the v1 golden set; tightening
# requires an ADR amendment.
FOOD_LOG_AUTO_INSERT_CONFIDENCE = 0.7

# HIGH-2: in-flight lock TTL (60s). Bounds the worst-case waste when a
# worker crashes mid-job. The waiter polls the cache for up to 30s before
# falling through to a normal provider call.
_INFLIGHT_LOCK_TTL_S = 60
_INFLIGHT_WAIT_S = 30
_INFLIGHT_KEY_FMT = "nova:vision:inflight:{sha}"


def _normalize_cache_result(
    result: object,
) -> tuple[list[DetectedFoodItem], str | None] | None:
    """Repo port returns (items, prompt_sha) — but some legacy/test doubles
    still return a bare list. Normalise here so the use case is robust."""
    if result is None:
        return None
    if isinstance(result, tuple) and len(result) == 2:
        items_raw, sha_raw = result
        items_list: list[DetectedFoodItem] = list(items_raw)
        sha: str | None = sha_raw if isinstance(sha_raw, str) else None
        return items_list, sha
    if isinstance(result, list):
        return list(result), None
    return None


@dataclass(slots=True)
class ProcessVisionJob:
    repo: VisionJobRepository
    provider: VisionProvider
    matcher: FoodMatcher
    notifier: JobNotifier
    bus: EventBus
    session: AsyncSession

    async def __call__(  # noqa: PLR0913, PLR0912, PLR0915 — orchestrator: pipeline stages are sequential (lock → cache → recognise → match → reconcile → persist → notify); splitting reduces clarity and forces dataclass plumbing for transient state.
        self,
        *,
        job_id: UUID,
        user_id: UUID,
        meal_time: Literal["breakfast", "lunch", "dinner", "snack"],
        image_bytes: bytes,
        mime: str,
        locale: str,
        region: str,
    ) -> None:
        start = datetime.now(UTC)
        await self.repo.mark_running(job_id)

        try:
            # --- SHA256 dedup cache (Capa 1) ---
            settings = get_settings()
            job_meta = await self.repo.get(job_id)
            image_sha = job_meta.image_sha256 if job_meta else ""
            items: list[DetectedFoodItem] = []
            prompt_sha: str = ""
            cache_hit = False

            # HIGH-1 (full wire): invalidate cache when prompt template
            # changes. Provider exposes current_prompt_sha256 via port.
            current_prompt_sha = self.provider.current_prompt_sha256(
                locale=locale,
                region=region,
            )
            cached = None
            if image_sha:
                cached = _normalize_cache_result(
                    await self.repo.find_recent_completed_by_sha(
                        image_sha256=image_sha,
                        ttl_days=settings.vision_cache_ttl_days,
                        current_prompt_sha256=current_prompt_sha,
                    )
                )

            if cached is not None:
                cache_hit = True
                VISION_CACHE_HITS.inc()
                cached_items, cached_prompt_sha = cached
                items = cached_items
                # HIGH-1: reuse the ORIGINAL prompt_sha so downstream audit
                # queries by prompt version stay correct. If the cached
                # row predates the prompt_sha column, fall back to the
                # job_meta's own prompt_sha (may be None — handled below).
                prompt_sha = (
                    cached_prompt_sha or (job_meta.prompt_sha256 if job_meta else None) or ""
                )
                log.info(
                    "vision.cache.hit",
                    job_id=str(job_id),
                    n_items=len(items),
                    prompt_sha=prompt_sha[:8] if prompt_sha else None,
                )
            else:
                # HIGH-2: serialise concurrent workers on the same SHA via a
                # Redis lock to avoid double-billing the provider.
                lock_key = _INFLIGHT_KEY_FMT.format(sha=image_sha) if image_sha else None
                acquired = True
                redis = get_redis() if lock_key else None
                if lock_key and redis is not None:
                    try:
                        acquired = bool(
                            await redis.set(
                                lock_key,
                                "1",
                                nx=True,
                                ex=_INFLIGHT_LOCK_TTL_S,
                            )
                        )
                    except Exception as rexc:  # noqa: BLE001
                        # Redis hiccup: degrade to non-locked path. The cost
                        # of a rare double-call is preferable to dropping
                        # the user request.
                        log.warning("vision.inflight.redis_down", err=str(rexc))
                        acquired = True

                try:
                    if not acquired:
                        # Another worker is processing this SHA. Poll the
                        # cache for up to _INFLIGHT_WAIT_S seconds.
                        waited_hit = None
                        for _ in range(_INFLIGHT_WAIT_S):
                            await asyncio.sleep(1)
                            waited = _normalize_cache_result(
                                await self.repo.find_recent_completed_by_sha(
                                    image_sha256=image_sha,
                                    ttl_days=settings.vision_cache_ttl_days,
                                    current_prompt_sha256=current_prompt_sha,
                                )
                            )
                            if waited is not None:
                                waited_hit = waited
                                break
                        if waited_hit is not None:
                            VISION_INFLIGHT_LOCK_WAITS.labels(outcome="hit").inc()
                            VISION_CACHE_HITS.inc()
                            cache_hit = True
                            items, cached_prompt_sha = waited_hit
                            prompt_sha = (
                                cached_prompt_sha
                                or (job_meta.prompt_sha256 if job_meta else None)
                                or ""
                            )
                        else:
                            # Lock holder likely crashed — proceed without lock.
                            VISION_INFLIGHT_LOCK_WAITS.labels(outcome="timeout").inc()
                            VISION_CACHE_MISSES.inc()
                            items, prompt_sha = await self.provider.recognise(
                                image_bytes=image_bytes,
                                mime=mime,
                                user_id=user_id,
                                locale=locale,
                                region=region,
                            )
                    else:
                        VISION_CACHE_MISSES.inc()
                        items, prompt_sha = await self.provider.recognise(
                            image_bytes=image_bytes,
                            mime=mime,
                            user_id=user_id,
                            locale=locale,
                            region=region,
                        )
                finally:
                    if acquired and lock_key and redis is not None:
                        try:
                            await redis.delete(lock_key)
                        except (
                            Exception
                        ) as exc:  # noqa: BLE001 — best-effort lock cleanup; TTL-bounded
                            log.debug(
                                "vision.lock_release_failed",
                                error=str(exc),
                                lock_key=lock_key,
                            )

            # CRITICAL-2: ALWAYS re-run matcher per user_id. Cache hits arrive
            # with matcher fields stripped at the repo layer; cache misses
            # produce raw LLM items with no match yet. Either way, the
            # FoodMatcher fires fresh against this user's catalog + personal
            # foods.
            for it in items:
                # Defensive: ensure any leaking personal field is wiped.
                it.matched_food_id = None
                it.matched_name_norm = None
                it.match_method = None
                food_id, name_norm, method = await self.matcher.match(
                    name=it.name,
                    amount_g=float(it.estimated_amount_g),
                    locale=locale,
                    user_id=user_id,
                )
                it.matched_food_id = food_id
                it.matched_name_norm = name_norm
                it.match_method = method

            # Persist food_logs (only items above the auto-insert confidence
            # threshold or with a strong catalog match land as automatic
            # logs; lower-confidence rows stay in detected_items for review).
            food_log_ids: list[UUID] = []
            total_kcal = sum(i.kcal for i in items)
            _ = cache_hit  # observability hook; keep for log enrichment later

            # ADR-0026 L1 — per-meal-slot cap. Counted by the number of
            # items that will actually land as food_logs rows. Photo jobs
            # cannot raise an HTTP error here (worker context); on cap
            # exhaust we log + skip the inserts to avoid silent XP gain.
            insertable = [
                it for it in items
                if it.confidence >= FOOD_LOG_AUTO_INSERT_CONFIDENCE
                or it.matched_food_id is not None
            ]
            if insertable:
                from app.gamification.infrastructure.anti_cheat_caps import (
                    FOOD_LOG_PER_SLOT_CAP,
                    check_and_increment_food_log_slot,
                )

                # Redis hiccup must not drop the user's photo log — match
                # the inflight-lock degradation pattern above.
                try:
                    slot_count = await check_and_increment_food_log_slot(
                        get_redis(),
                        user_id,
                        date.today(),
                        meal_time,
                        amount=len(insertable),
                    )
                except Exception as rexc:  # noqa: BLE001
                    log.warning(
                        "vision.slot_cap.redis_down", err=str(rexc)
                    )
                    slot_count = 0
                if slot_count > FOOD_LOG_PER_SLOT_CAP:
                    log.warning(
                        "vision.meal_slot_log_cap_exceeded",
                        extra={
                            "user_id": str(user_id),
                            "meal_slot": meal_time,
                            "current": slot_count,
                            "cap": FOOD_LOG_PER_SLOT_CAP,
                            "job_id": str(job_id),
                        },
                    )
                    insertable = []

            for it in insertable:
                flog_id = uuid4()
                await self.session.execute(
                    text(
                        """
                    INSERT INTO food_logs (
                        id, user_id, date, meal_time, food_id, free_text_name,
                        amount_g, kcal, protein_g, carbs_g, fat_g, method,
                        confidence, prompt_sha256, created_at
                    ) VALUES (
                        :id, :uid, :d, :mt, :fid, :ftn,
                        :ag, :kc, :pg, :cg, :fg, 'photo',
                        :conf, :psha, now()
                    )
                """
                    ),
                    {
                        "id": str(flog_id),
                        "uid": str(user_id),
                        "d": date.today(),
                        "mt": meal_time,
                        "fid": str(it.matched_food_id) if it.matched_food_id else None,
                        "ftn": it.name if it.matched_food_id is None else None,
                        "ag": float(it.estimated_amount_g),
                        "kc": it.kcal,
                        "pg": it.protein_g,
                        "cg": it.carbs_g,
                        "fg": it.fat_g,
                        "conf": it.confidence,
                        "psha": prompt_sha,
                    },
                )
                food_log_ids.append(flog_id)

            await self.repo.mark_completed(job_id, items=items)

            now = datetime.now(UTC)
            VISION_JOB_DURATION.observe((now - start).total_seconds())

            await self.bus.publish(
                VisionJobCompleted(
                    job_id=job_id,
                    user_id=user_id,
                    n_items=len(items),
                    total_kcal=total_kcal,
                    at=now,
                )
            )
            # FoodPhotoLogged — for coach cross-check + gamification.
            await self.bus.publish(
                FoodPhotoLogged(
                    user_id=user_id,
                    meal_time=meal_time,
                    kcal=total_kcal,
                    food_log_ids=tuple(food_log_ids),
                    detected_names=tuple(i.name for i in items),
                    at=now,
                )
            )
            await self.notifier.notify(
                user_id=user_id,
                channel="vision",
                payload={"job_id": str(job_id), "status": "completed", "n_items": len(items)},
            )
            log.info("vision.process.done", job_id=str(job_id), n=len(items))

        except Exception as exc:  # noqa: BLE001
            err_code = exc.__class__.__name__
            await self.repo.mark_failed(job_id, error_code=err_code, detail=str(exc)[:300])
            await self.bus.publish(
                VisionJobFailed(
                    job_id=job_id,
                    user_id=user_id,
                    error_code=err_code,
                    at=datetime.now(UTC),
                )
            )
            await self.notifier.notify(
                user_id=user_id,
                channel="vision",
                payload={"job_id": str(job_id), "status": "failed"},
            )
            log.warning("vision.process.failed", job_id=str(job_id), err=err_code)
            raise
