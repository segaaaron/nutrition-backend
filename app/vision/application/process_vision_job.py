"""Worker use case — orchestrates the vision pipeline for one VisionJob.

Pipeline (each stage is a single-responsibility method or infrastructure call):
  1. _recognise          — SHA dedup → pHash near-dup → inflight lock → provider
  2. _match_and_ground   — per-user catalog match + macro grounding (always reruns)
  3. _maybe_escalate     — post-catalog escalation to full model when needed
  4. _triangulate_mains  — top-down catalog anchor + physics arbiter
  5. _apply_plan_anchor  — scale items to planned meal kcal when within ±15 %
  6. decompose           — plate decomposition: clamping, inference, honest totals
  7. persist_food_logs   — slot-cap check + INSERT food_logs (infra module)
  8. _publish_completion — mark_completed + domain events + client notify

Failure path: _handle_failure (mark_failed + VisionJobFailed + notify).

SQL / Redis concerns live in app/vision/infrastructure/:
  macro_grounder.py   — ground_macros_from_db, apply_group_fallback, reconcile_kcal_atwater
  plan_context.py     — load_plan_context
  user_context.py     — load_user_profile, load_portion_calibration
  food_log_writer.py  — persist_food_logs
  inflight_lock.py    — acquire_lock, release_lock, poll_until_cached
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Literal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.event_bus import EventBus
from app.core.logging import get_logger
from app.core.metrics import VISION_CACHE_HITS, VISION_CACHE_MISSES, VISION_JOB_DURATION
from app.core.redis import get_redis
from app.imaging.infrastructure.phash import compute_phash_64
from app.vision.application.reconcile_with_plan import ReconcileWithPlan
from app.vision.domain.entities import DetectedFoodItem
from app.vision.domain.events import FoodPhotoLogged, VisionJobCompleted, VisionJobFailed
from app.vision.domain.plate_decomposition import decompose
from app.vision.domain.ports import FoodMatcher, JobNotifier, VisionJobRepository, VisionProvider
from app.vision.domain.triangulation import arbitrate
from app.vision.infrastructure import inflight_lock as _lock
from app.vision.infrastructure.cache_normalizer import normalize_cache_result
from app.vision.infrastructure.food_log_writer import persist_food_logs as _persist
from app.vision.infrastructure.macro_grounder import (
    apply_group_fallback,
    ground_macros_from_db,
    reconcile_kcal_atwater,
)
from app.vision.infrastructure.plan_context import load_plan_context
from app.vision.infrastructure.user_context import (
    load_portion_calibration,
    load_recent_portion_anchors,
    load_user_profile,
)

log = get_logger("vision.process")

_ESCALATE_MIN_ITEM_CONF: float = 0.35


def needs_full_model(
    items: list[DetectedFoodItem], *, conf_threshold: float = 0.0
) -> tuple[bool, str]:
    """Pipeline-level escalation decision (pure).  Returns (escalate, reason)."""
    if not items:
        return True, "empty"
    if min(i.confidence for i in items) < _ESCALATE_MIN_ITEM_CONF:
        return True, "very_low_item_confidence"
    return False, ""


# Alias so existing tests that import _normalize_cache_result keep working.
_normalize_cache_result = normalize_cache_result


# ------------------------------------------------------------------ #
# Use case                                                            #
# ------------------------------------------------------------------ #

@dataclass(slots=True)
class ProcessVisionJob:
    repo: VisionJobRepository
    provider: VisionProvider
    matcher: FoodMatcher
    notifier: JobNotifier
    bus: EventBus
    session: AsyncSession

    async def __call__(
        self,
        *,
        job_id: UUID,
        user_id: UUID,
        meal_time: Literal["breakfast", "lunch", "dinner", "snack"],
        image_bytes: bytes,
        mime: str,
        locale: str,
        region: str,
        user_context: str | None = None,
    ) -> None:
        """Orchestrate the full vision pipeline for one job."""
        start = datetime.now(UTC)
        await self.repo.mark_running(job_id)

        try:
            settings = get_settings()
            job_meta = await self.repo.get(job_id)
            image_sha = job_meta.image_sha256 if job_meta else ""
            current_prompt_sha = self.provider.current_prompt_sha256(
                locale=locale, region=region,
            )

            # Sequential — MUST NOT gather: these three share `self.session`,
            # and one async session (single connection) is not concurrency-safe.
            # Firing them via asyncio.gather interleaves queries on the same
            # connection → SQLAlchemy IllegalStateChangeError (the exact race
            # that broke plan generation, create_plan.py). A shared connection
            # serialises anyway, so gather bought no parallelism — only the race.
            plan_context = await load_plan_context(
                user_id=user_id, meal_time=meal_time, session=self.session
            )
            user_profile = await load_user_profile(user_id=user_id, session=self.session)
            portion_anchors = await load_recent_portion_anchors(
                user_id=user_id, session=self.session
            )

            items, prompt_sha, cache_hit = await self._recognise(
                job_id=job_id,
                image_sha=image_sha,
                image_bytes=image_bytes,
                mime=mime,
                user_id=user_id,
                locale=locale,
                region=region,
                job_meta=job_meta,
                settings=settings,
                current_prompt_sha=current_prompt_sha,
                plan_context=plan_context,
                user_profile=user_profile,
                portion_anchors=portion_anchors,
                user_context=user_context,
            )

            await self._match_and_ground(items, locale=locale, user_id=user_id)

            if not cache_hit and settings.vision_cascade_enabled and items:
                items, prompt_sha = await self._maybe_escalate(
                    items,
                    prompt_sha=prompt_sha,
                    image_bytes=image_bytes,
                    mime=mime,
                    user_id=user_id,
                    locale=locale,
                    region=region,
                    plan_context=plan_context,
                    user_profile=user_profile,
                    portion_anchors=portion_anchors,
                    settings=settings,
                    user_context=user_context,
                )

            await self._triangulate_mains(items)
            await self._apply_plan_anchor(items, user_id=user_id, meal_time=meal_time)
            items, plate_totals = decompose(items)

            food_log_ids = await _persist(
                items,
                user_id=user_id,
                meal_time=meal_time,
                prompt_sha=prompt_sha,
                session=self.session,
            )

            await self.repo.mark_completed(job_id, items=items)
            await self._publish_completion(
                job_id=job_id,
                user_id=user_id,
                meal_time=meal_time,
                items=items,
                plate_totals=plate_totals,
                food_log_ids=food_log_ids,
                start=start,
            )
            log.info("vision.process.done", job_id=str(job_id), n=len(items))

        except Exception as exc:  # noqa: BLE001 — OK2: worker top-level; re-raises after cleanup
            await self._handle_failure(job_id=job_id, user_id=user_id, exc=exc)
            raise

    # ------------------------------------------------------------------ #
    # Stage 1 — Recognition                                               #
    # ------------------------------------------------------------------ #

    async def _recognise(
        self,
        *,
        job_id: UUID,
        image_sha: str,
        image_bytes: bytes,
        mime: str,
        user_id: UUID,
        locale: str,
        region: str,
        job_meta: object,
        settings: object,
        current_prompt_sha: str,
        plan_context: str | None,
        user_profile: dict | None,
        portion_anchors: list[str] | None = None,
        user_context: str | None = None,
    ) -> tuple[list[DetectedFoodItem], str, bool]:
        """SHA dedup → pHash near-dup → inflight lock → provider.

        Returns (items, prompt_sha, cache_hit).
        """
        # Layer 1 — SHA dedup (cross-user, PII-stripped)
        if image_sha:
            sha_hit = _normalize_cache_result(
                await self.repo.find_recent_completed_by_sha(
                    image_sha256=image_sha,
                    ttl_days=settings.vision_cache_ttl_days,
                    current_prompt_sha256=current_prompt_sha,
                )
            )
            if sha_hit is not None:
                VISION_CACHE_HITS.inc()
                cached_items, cached_sha = sha_hit
                await self._save_phash_best_effort(
                    job_id=job_id,
                    phash=await self._compute_phash(image_bytes),
                )
                log.info("vision.cache.hit", n_items=len(cached_items))
                return (
                    cached_items,
                    cached_sha or (getattr(job_meta, "prompt_sha256", None) or ""),
                    True,
                )

        # Layer 2 — pHash near-dup (per-user)
        phash = await self._compute_phash(image_bytes)
        if phash is not None:
            finder = getattr(self.repo, "find_recent_completed_by_phash", None)
            if finder is not None:
                near_hit = _normalize_cache_result(
                    await finder(
                        user_id=user_id,
                        phash_64=phash,
                        ttl_days=settings.vision_cache_ttl_days,
                        current_prompt_sha256=current_prompt_sha,
                    )
                )
                if near_hit is not None:
                    VISION_CACHE_HITS.inc()
                    near_items, near_sha = near_hit
                    log.info("vision.phash.near_dup_hit", n_items=len(near_items))
                    await self._save_phash_best_effort(job_id=job_id, phash=phash)
                    return near_items, near_sha or current_prompt_sha, True

        await self._save_phash_best_effort(job_id=job_id, phash=phash)

        # Layer 3 — inflight lock → provider
        VISION_CACHE_MISSES.inc()
        redis = get_redis() if image_sha else None
        acquired = await _lock.acquire_lock(image_sha, redis) if redis else True

        try:
            if not acquired:
                waited = await _lock.poll_until_cached(
                    image_sha,
                    repo=self.repo,
                    settings=settings,
                    current_prompt_sha=current_prompt_sha,
                    job_meta=job_meta,
                )
                if waited is not None:
                    return waited[0], waited[1], True

            stage = "primary_only" if settings.vision_cascade_enabled else "auto"
            items, prompt_sha = await self.provider.recognise(
                image_bytes=image_bytes,
                mime=mime,
                user_id=user_id,
                locale=locale,
                region=region,
                stage=stage,
                plan_context=plan_context,
                user_profile=user_profile,
                portion_history=portion_anchors or [],
                user_context=user_context,
            )
            return items, prompt_sha, False
        finally:
            if acquired and redis is not None:
                await _lock.release_lock(image_sha, redis)

    # ------------------------------------------------------------------ #
    # Stage 2 — Match & ground                                            #
    # ------------------------------------------------------------------ #

    async def _match_item(
        self,
        it: DetectedFoodItem,
        *,
        locale: str,
        user_id: UUID,
        calibration: dict[str, float],
    ) -> None:
        """Match + portion-calibrate one item.

        Safe for concurrent gather: production matcher opens its own session
        per call (session_factory path in HybridFoodMatcher).
        """
        it.matched_food_id = None
        it.matched_name_norm = None
        it.match_method = None
        food_id, name_norm, method, corrected_g = await self.matcher.match(
            name=it.name,
            amount_g=float(it.estimated_amount_g),
            locale=locale,
            user_id=user_id,
        )
        it.matched_food_id = food_id
        it.matched_name_norm = name_norm
        it.match_method = method

        if corrected_g is not None and corrected_g > 0:
            it.estimated_amount_g = Decimal(str(round(corrected_g, 1)))
        elif calibration and it.food_group and food_id is None and not it.inferred:
            ratio = calibration.get(it.food_group)
            if ratio is not None and 0.1 <= ratio <= 10.0:
                it.estimated_amount_g = (
                    it.estimated_amount_g * Decimal(str(ratio))
                ).quantize(Decimal("0.1"), rounding=ROUND_HALF_EVEN)

    async def _match_and_ground(
        self, items: list[DetectedFoodItem], *, locale: str, user_id: UUID
    ) -> None:
        """Per-user catalog match + macro grounding for every item.

        Match calls fan-out concurrently — each opens its own DB session via
        the matcher's session_factory so there is no shared-session conflict.
        """
        calibration = await load_portion_calibration(user_id=user_id, session=self.session)
        await asyncio.gather(
            *[
                self._match_item(it, locale=locale, user_id=user_id, calibration=calibration)
                for it in items
            ]
        )
        await ground_macros_from_db(items, session=self.session)
        await apply_group_fallback(items)
        # Final coherence guard: repair only GROSS kcal↔macro drift, preserving
        # USDA's food-specific Atwater factors (see reconcile_kcal_atwater).
        reconcile_kcal_atwater(items)

    # ------------------------------------------------------------------ #
    # Stage 3 — Grounded escalation                                       #
    # ------------------------------------------------------------------ #

    async def _maybe_escalate(
        self,
        items: list[DetectedFoodItem],
        *,
        prompt_sha: str,
        image_bytes: bytes,
        mime: str,
        user_id: UUID,
        locale: str,
        region: str,
        plan_context: str | None,
        user_profile: dict | None,
        portion_anchors: list[str] | None = None,
        settings: object,
        user_context: str | None = None,
    ) -> tuple[list[DetectedFoodItem], str]:
        """Post-catalog escalation: call full model only when catalog cannot vouch."""
        escalate, esc_reason = needs_full_model(
            items, conf_threshold=settings.vision_confidence_threshold
        )
        if not escalate:
            return items, prompt_sha

        log.info("vision.grounded_escalation", reason=esc_reason, n_primary=len(items))
        new_items, new_prompt_sha = await self.provider.recognise(
            image_bytes=image_bytes,
            mime=mime,
            user_id=user_id,
            locale=locale,
            region=region,
            stage="full_only",
            plan_context=plan_context,
            user_profile=user_profile,
            portion_history=portion_anchors or [],
            user_context=user_context,
        )
        await self._match_and_ground(new_items, locale=locale, user_id=user_id)
        return new_items, new_prompt_sha

    # ------------------------------------------------------------------ #
    # Stage 4 — Triangulate mains                                         #
    # ------------------------------------------------------------------ #

    _TRIANGULATE_ROLES = frozenset({"main", "sauce", "condiment", "cooking_fat"})

    async def _triangulate_mains(self, items: list[DetectedFoodItem]) -> None:
        """Top-down catalog anchor + physics arbiter for high-cal roles (F5.1)."""
        try:
            from app.vision.infrastructure.dish_anchor import SqlDishAnchor

            anchor_repo = SqlDishAnchor(self.session)
            for idx, it in enumerate(items):
                if it.role not in self._TRIANGULATE_ROLES or it.inferred:
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
        except Exception as exc:  # noqa: BLE001 — OK4: triangulation best-effort; never blocks pipeline
            log.warning("vision.triangulation.failed", err=str(exc))

    # ------------------------------------------------------------------ #
    # Stage 5 — Plan anchor                                               #
    # ------------------------------------------------------------------ #

    async def _apply_plan_anchor(
        self, items: list[DetectedFoodItem], *, user_id: UUID, meal_time: str
    ) -> None:
        """Scale item kcal to planned meal kcal when within ±15 % (F2.2)."""
        try:
            detected_kcal = sum(it.kcal for it in items if not it.inferred)
            if detected_kcal <= 0:
                return

            hint = await ReconcileWithPlan(self.session)(
                user_id=user_id, meal_time=meal_time, detected_kcal=detected_kcal,
            )
            if hint is None or hint["needs_hint"]:
                return

            planned_kcal: int = hint["planned_kcal"]
            if planned_kcal <= 0:
                return

            scale = planned_kcal / detected_kcal
            for it in items:
                if it.inferred:
                    continue
                it.kcal = round(it.kcal * scale)
                it.kcal_min = round(it.kcal * 0.90)
                it.kcal_max = round(it.kcal * 1.10)
                it.protein_g = round(float(it.protein_g) * scale)
                it.carbs_g = round(float(it.carbs_g) * scale)
                it.fat_g = round(float(it.fat_g) * scale)
                it.fiber_g = round(float(it.fiber_g) * scale)
                it.sugar_g = round(float(it.sugar_g) * scale)

            log.info(
                "vision.plan_anchor.applied",
                user_id=str(user_id),
                meal_time=meal_time,
                scale=round(scale, 3),
            )
        except Exception as exc:  # noqa: BLE001 — OK4: plan anchor best-effort; LLM estimates remain
            log.debug("vision.plan_anchor.failed", err=str(exc)[:120])

    # ------------------------------------------------------------------ #
    # Completion & failure                                                #
    # ------------------------------------------------------------------ #

    async def _publish_completion(
        self,
        *,
        job_id: UUID,
        user_id: UUID,
        meal_time: str,
        items: list[DetectedFoodItem],
        plate_totals: object,
        food_log_ids: list[UUID],
        start: datetime,
    ) -> None:
        now = datetime.now(UTC)
        VISION_JOB_DURATION.observe((now - start).total_seconds())

        await self.bus.publish(
            VisionJobCompleted(
                job_id=job_id,
                user_id=user_id,
                n_items=len(items),
                total_kcal=plate_totals.kcal,
                at=now,
            )
        )
        await self.bus.publish(
            FoodPhotoLogged(
                user_id=user_id,
                meal_time=meal_time,
                kcal=plate_totals.kcal,
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
                "kcal": plate_totals.kcal,
                "kcal_min": plate_totals.kcal_min,
                "kcal_max": plate_totals.kcal_max,
                "confidence": plate_totals.confidence,
            },
        )

    async def _handle_failure(
        self, *, job_id: UUID, user_id: UUID, exc: Exception
    ) -> None:
        err_code = exc.__class__.__name__
        await self.repo.mark_failed(job_id, error_code=err_code, detail=str(exc)[:300])
        await self.bus.publish(
            VisionJobFailed(
                job_id=job_id, user_id=user_id, error_code=err_code, at=datetime.now(UTC),
            )
        )
        await self.notifier.notify(
            user_id=user_id,
            channel="vision",
            payload={"job_id": str(job_id), "status": "failed"},
        )
        log.warning("vision.process.failed", job_id=str(job_id), err=err_code)

    # ------------------------------------------------------------------ #
    # Helpers                                                             #
    # ------------------------------------------------------------------ #

    async def _compute_phash(self, image_bytes: bytes) -> int | None:
        try:
            return await asyncio.to_thread(compute_phash_64, image_bytes)
        except Exception as exc:  # noqa: BLE001 — OK4: pHash dedup metadata; never blocks pipeline
            log.debug("vision.phash.compute_failed", err=str(exc))
            return None

    async def _save_phash_best_effort(
        self, job_id: UUID | None, phash: int | None
    ) -> None:
        if phash is None or job_id is None:
            return
        saver = getattr(self.repo, "save_phash", None)
        if saver is None:
            return
        try:
            await saver(job_id, phash)
        except Exception as exc:  # noqa: BLE001 — OK4: phash write; never blocks pipeline
            log.debug("vision.phash.save_failed", err=str(exc))
