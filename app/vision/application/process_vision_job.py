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
from datetime import UTC, datetime
from decimal import ROUND_HALF_EVEN, Decimal
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
from app.imaging.infrastructure.phash import compute_phash_64
from app.shared.domain.time import utc_today
from app.vision.domain.entities import DetectedFoodItem
from app.vision.domain.events import FoodPhotoLogged, VisionJobCompleted, VisionJobFailed
from app.vision.domain.plate_decomposition import decompose
from app.vision.domain.ports import FoodMatcher, JobNotifier, VisionJobRepository, VisionProvider
from app.vision.domain.triangulation import arbitrate

log = get_logger("vision.process")

# LOW fix: confidence floor for auto-insert into food_logs. Items below
# this AND without a catalog match stay in detected_items JSONB for user
# review. Threshold is calibrated against the v1 golden set; tightening
# requires an ADR amendment.
FOOD_LOG_AUTO_INSERT_CONFIDENCE = 0.7

# Grounded escalation thresholds (2026-06-11). After catalog grounding,
# the cheap model's output is escalated to the heavy model only when the
# catalog could not vouch for it: any item with truly unusable confidence,
# or low average confidence COMBINED with a mostly-unmatched plate. A
# low-confidence but well-matched plate keeps the cheap result — grounding
# already replaced its macros with audited per-100g values.
_ESCALATE_MIN_ITEM_CONF = 0.35
_ESCALATE_UNMATCHED_RATIO = 0.4


def needs_full_model(
    items: list[DetectedFoodItem], *, conf_threshold: float
) -> tuple[bool, str]:
    """Pipeline-level escalation decision (pure). Returns (escalate, reason)."""
    if not items:
        return True, "empty"
    confidences = [i.confidence for i in items]
    if min(confidences) < _ESCALATE_MIN_ITEM_CONF:
        return True, "very_low_item_confidence"
    unmatched = [i for i in items if i.matched_food_id is None]
    unmatched_ratio = len(unmatched) / len(items)
    avg_conf = sum(confidences) / len(confidences)
    if avg_conf < conf_threshold and unmatched_ratio > _ESCALATE_UNMATCHED_RATIO:
        return True, "low_confidence_unmatched"
    return False, ""


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
                # Persist the perceptual hash on SHA hits too: byte-identical
                # re-uploads are the cheapest photo-farming pattern, and the
                # anomaly pHash-clustering signal only sees rows that carry
                # phash_64 (QA 2026-06-12).
                try:
                    sha_hit_phash = await asyncio.to_thread(
                        compute_phash_64, image_bytes
                    )
                    await self._save_phash_best_effort(job_id, sha_hit_phash)
                except Exception as pexc:  # noqa: BLE001 — OK4: observability metadata only
                    log.debug("vision.phash.sha_hit_failed", err=str(pexc))
            else:
                # Near-duplicate dedup via perceptual hash (cost lever,
                # 2026-06-11). SHA missed — but the user may have just
                # re-photographed the SAME plate (blur retry, new angle,
                # identical daily breakfast): different bytes, same scene.
                # aHash Hamming ≤5 within this user's recent completed
                # jobs reuses the prior result for $0. Best-effort: any
                # failure (libvips absent, repo without the method in
                # test doubles) falls through to the normal provider path.
                phash: int | None = None
                try:
                    phash = await asyncio.to_thread(compute_phash_64, image_bytes)
                    finder = getattr(self.repo, "find_recent_completed_by_phash", None)
                    if phash is not None and finder is not None:
                        near = _normalize_cache_result(
                            await finder(
                                user_id=user_id,
                                phash_64=phash,
                                ttl_days=settings.vision_cache_ttl_days,
                                current_prompt_sha256=current_prompt_sha,
                            )
                        )
                        if near is not None:
                            cache_hit = True
                            VISION_CACHE_HITS.inc()
                            items, near_prompt_sha = near
                            prompt_sha = near_prompt_sha or current_prompt_sha
                            log.info(
                                "vision.phash.near_dup_hit",
                                job_id=str(job_id),
                                n_items=len(items),
                            )
                except Exception as pexc:  # noqa: BLE001 — OK4: pHash dedup is a best-effort cost optimization; never blocks the provider path
                    log.debug("vision.phash.lookup_failed", err=str(pexc))

                await self._save_phash_best_effort(job_id, phash)
                # Grounded escalation: with the cascade on, ask the provider
                # for the cheap model ONLY — the escalate decision moves to
                # the pipeline, after catalog grounding (see below).
                provider_stage = (
                    "primary_only" if settings.vision_cascade_enabled else "auto"
                )
                if cache_hit:
                    # pHash near-dup hit — skip the provider entirely.
                    lock_key = None
                else:
                    # HIGH-2: serialise concurrent workers on the same SHA
                    # via a Redis lock to avoid double-billing the provider.
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
                    if cache_hit:
                        # pHash near-dup already supplied the items —
                        # provider call skipped entirely.
                        pass
                    elif not acquired:
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
                                stage=provider_stage,
                            )
                    else:
                        VISION_CACHE_MISSES.inc()
                        items, prompt_sha = await self.provider.recognise(
                            image_bytes=image_bytes,
                            mime=mime,
                            user_id=user_id,
                            locale=locale,
                            region=region,
                            stage=provider_stage,
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
            # foods. Grounding then replaces the LLM's kcal arithmetic with
            # audited per-100g values (see _match_and_ground).
            await self._match_and_ground(items, locale=locale, user_id=user_id)

            # GROUNDED ESCALATION (cost lever, 2026-06-11). When the cheap
            # primary model ran (stage="primary_only"), the escalate-or-not
            # decision happens HERE — after catalog grounding — instead of
            # inside the provider. Rationale: the old internal cascade
            # escalated on raw confidence alone, but a low-confidence item
            # whose name MATCHED the catalog already got its macros fixed
            # by grounding; paying the heavy model for it is wasted spend.
            # Only escalate when the catalog could NOT vouch for the output.
            if (
                not cache_hit
                and settings.vision_cascade_enabled
                and items is not None
            ):
                escalate, esc_reason = needs_full_model(
                    items, conf_threshold=settings.vision_confidence_threshold
                )
                if escalate:
                    log.info(
                        "vision.grounded_escalation",
                        job_id=str(job_id),
                        reason=esc_reason,
                        n_items_primary=len(items),
                    )
                    items, prompt_sha = await self.provider.recognise(
                        image_bytes=image_bytes,
                        mime=mime,
                        user_id=user_id,
                        locale=locale,
                        region=region,
                        stage="full_only",
                    )
                    await self._match_and_ground(
                        items, locale=locale, user_id=user_id
                    )

            # TRIANGULATION (Fase 2): second, independent opinion for main
            # dishes — the recipe catalog's kcal scaled to the estimated
            # portion, reconciled by the physics arbiter (density bands).
            # Best-effort: anchor lookup failure leaves bottom-up values.
            await self._triangulate_mains(items)

            # Plate Decomposition 2.0 post-pass (pure domain): clamp dry
            # spices to ≤5 kcal (LLM hallucinates calories for a pinch of
            # comino), condiment kcal floors, infer absorbed cooking oil /
            # hidden dairy (cream soups, purées, LatAm rice), beverage
            # engine (containers + alcohol formula), and honest totals
            # (kcal_min/best/max). Inferred items carry confidence 0.5 <
            # auto-insert threshold, so they land in detected_items for
            # user review — never silently in food_logs.
            items, plate_totals = decompose(items)

            # Persist food_logs (only items above the auto-insert confidence
            # threshold or with a strong catalog match land as automatic
            # logs; lower-confidence rows stay in detected_items for review).
            food_log_ids: list[UUID] = []
            total_kcal = plate_totals.kcal
            _ = cache_hit  # observability hook; keep for log enrichment later

            # ADR-0026 L1 — per-meal-slot cap. Counted by LOG EVENTS (one
            # photo submission = 1), NOT by detected ingredients (fixed
            # 2026-06-10: a single real plate yields 5-10 items, so counting
            # items blocked legitimate meals — 8-ingredient dinner logged
            # nothing and burned the whole slot quota). Photo jobs cannot
            # raise an HTTP error here (worker context); on cap exhaust we
            # log + skip the inserts to avoid silent XP gain.
            insertable = [
                it for it in items
                # Inferred items (hidden oil/cream estimates) NEVER auto-log,
                # even when the matcher pairs them with a real catalog food
                # — e.g. a cached replay re-matching "aceite de cocción
                # (estimado)" to real oil would otherwise double-log kcal
                # the original run never inserted (QA 2026-06-12).
                if not it.inferred
                and (
                    it.confidence >= FOOD_LOG_AUTO_INSERT_CONFIDENCE
                    or it.matched_food_id is not None
                )
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
                        utc_today(),
                        meal_time,
                        amount=1,
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
                        "d": utc_today(),
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
                payload={
                    "job_id": str(job_id),
                    "status": "completed",
                    "n_items": len(items),
                    # Honest calorie range (Plate Decomposition 2.0) —
                    # additive fields; older clients ignore them.
                    "kcal": plate_totals.kcal,
                    "kcal_min": plate_totals.kcal_min,
                    "kcal_max": plate_totals.kcal_max,
                    "confidence": plate_totals.confidence,
                },
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

    async def _match_and_ground(
        self, items: list[DetectedFoodItem], *, locale: str, user_id: UUID
    ) -> None:
        """Per-user catalog match + DB macro grounding for every item.

        Matching ALWAYS reruns per user (CRITICAL-2: cached items arrive
        with matcher fields stripped). Grounding replaces the LLM's kcal
        arithmetic with audited foods-per-100g × estimated grams.
        """
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
        await self._ground_matched_macros(items)

    async def _triangulate_mains(self, items: list[DetectedFoodItem]) -> None:
        """Top-down catalog anchor + physics arbiter for main dishes.

        Only `role == "main"` items get the anchor lookup AND the physics
        clamp (sides/sauces are too generic to match recipes, and their
        density bands overlap too much to clamp safely). Best-effort:
        any failure leaves bottom-up values untouched.
        """
        try:
            from app.vision.infrastructure.dish_anchor import SqlDishAnchor

            anchor_repo = SqlDishAnchor(self.session)
            for idx, it in enumerate(items):
                if it.role != "main" or it.inferred:
                    continue
                anchor = await anchor_repo.lookup(it.name)
                if anchor is None:
                    continue
                refined = arbitrate(it, anchor)
                if refined.kcal != it.kcal:
                    log.info(
                        "vision.triangulation.adjusted",
                        name=it.name[:60],
                        kcal_bottom_up=it.kcal,
                        kcal_final=refined.kcal,
                        anchor_sim=round(anchor.similarity, 2),
                    )
                items[idx] = refined
        except Exception as exc:  # noqa: BLE001 — OK4: triangulation is a best-effort accuracy layer; never blocks the pipeline
            log.warning("vision.triangulation.failed", err=str(exc))

    async def _save_phash_best_effort(self, job_id: UUID, phash: int | None) -> None:
        """Persist the job's perceptual hash so future photos can near-dup
        against it (and the anomaly pHash-clustering signal gets data).
        Best-effort: repo doubles in tests may lack the method."""
        if phash is None:
            return
        saver = getattr(self.repo, "save_phash", None)
        if saver is None:
            return
        try:
            await saver(job_id, phash)
        except Exception as exc:  # noqa: BLE001 — OK4: observability/dedup metadata write; never blocks the pipeline
            log.debug("vision.phash.save_failed", err=str(exc))

    async def _ground_matched_macros(self, items: list[DetectedFoodItem]) -> None:
        """Recompute macros from the audited foods table for matched items.

        foods.{kcal,protein_g,carbs_g,fat_g} are per-100g (same contract the
        voice flow scales by). One batched SELECT; Decimal math with
        banker's rounding (CLAUDE.md non-negotiable #2). Items whose DB
        kcal disagrees with the LLM estimate by >3× in either direction
        keep the LLM value — that gap signals a wrong MATCH, not a wrong
        estimate, and grounding to the wrong food is worse than not
        grounding at all.
        """
        matched = [it for it in items if it.matched_food_id is not None]
        if not matched:
            return
        ids = list({str(it.matched_food_id) for it in matched})
        try:
            rows = (
                await self.session.execute(
                    text(
                        """
                        SELECT id, COALESCE(kcal, 0), COALESCE(protein_g, 0),
                               COALESCE(carbs_g, 0), COALESCE(fat_g, 0)
                          FROM foods
                         WHERE id = ANY(CAST(:ids AS uuid[]))
                        """
                    ),
                    {"ids": ids},
                )
            ).all()
            per100 = {row[0]: (row[1], row[2], row[3], row[4]) for row in rows}
        except Exception as exc:  # noqa: BLE001 — OK4: grounding is a best-effort accuracy enhancement; a foods lookup failure must not fail the photo job (LLM estimates remain).
            log.warning("vision.ground.lookup_failed", err=str(exc))
            return

        for it in matched:
            macro = per100.get(it.matched_food_id)
            if macro is None or not macro[0]:
                continue  # no audited kcal for this food — keep LLM value
            factor = Decimal(str(it.estimated_amount_g)) / Decimal("100")

            def _scale(v: object, _f: Decimal = factor) -> int:
                return int(
                    (Decimal(str(v)) * _f).quantize(
                        Decimal("1"), rounding=ROUND_HALF_EVEN
                    )
                )

            kcal_db = _scale(macro[0])
            if kcal_db <= 0:
                continue
            # Wrong-match guard: >3× disagreement → distrust the match.
            if it.kcal > 0 and not (it.kcal / 3 <= kcal_db <= it.kcal * 3):
                log.info(
                    "vision.ground.match_disagreement",
                    name=it.name[:60],
                    kcal_llm=it.kcal,
                    kcal_db=kcal_db,
                    method=it.match_method,
                )
                continue
            it.kcal = kcal_db
            it.protein_g = _scale(macro[1])
            it.carbs_g = _scale(macro[2])
            it.fat_g = _scale(macro[3])
            # Composition is now ground truth; residual uncertainty is
            # portion size only → tighten the range to ±20%.
            it.kcal_min = int(round(kcal_db * 0.8))
            it.kcal_max = int(round(kcal_db * 1.2))
