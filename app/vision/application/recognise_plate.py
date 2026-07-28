"""Application service: two-pass vision recognition.

Owns the call sequence (identify → hint → estimate), merge, and degradation.
Lives in application layer — orchestration policy does not belong in infrastructure.
"""
from __future__ import annotations

import asyncio
import hashlib
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from app.core.config import get_settings
from app.core.errors import CostCapExceeded
from app.core.logging import get_logger
from app.vision.domain.entities import DetectedFoodItem
from app.vision.domain.ports import (
    PortionHintSource,
    VisionEstimationProvider,
    VisionIdentificationProvider,
)
from app.vision.domain.value_objects import FoodIdentification, PortionEstimate, PortionHint

log = get_logger("vision.recognise_plate")


def _median_decimal(values: list[Decimal]) -> Decimal:
    """Compute the median of a non-empty list of Decimal values.

    For even-length lists returns the mean of the two central values.
    Pure function — no I/O, no state.
    """
    sorted_vals = sorted(values)
    n = len(sorted_vals)
    mid = n // 2
    if n % 2 == 0:
        return (sorted_vals[mid - 1] + sorted_vals[mid]) / 2
    return sorted_vals[mid]


@dataclass(frozen=True, slots=True)
class RecognitionContext:
    image_bytes: bytes
    mime: str
    user_id: UUID | None
    locale: str
    region: str
    meal_time: str | None = None
    plan_context: str | None = None
    user_context: str | None = None
    user_profile: dict[str, object] | None = None
    portion_history: list[str] | None = None
    model_override: str | None = None  # forces specific model on both calls


@dataclass(frozen=True, slots=True)
class RecognitionOutcome:
    items: tuple[DetectedFoodItem, ...]
    prompt_sha256: str          # sha256(identify_sha + ":" + estimate_sha)
    identification_conf_avg: float
    estimation_conf_avg: float
    degraded: bool              # True = Call 2 failed, catalog medians used


@dataclass(slots=True)
class RecognisePlate:
    """Two-pass vision: Call 1 identifies, Call 2 estimates grams.

    Call 2 ALWAYS runs — conditional Call 2 reinstates the coupled task that
    produces both-axes failures (see sprint S2.1 §0 analysis).
    """

    identifier: VisionIdentificationProvider
    estimator: VisionEstimationProvider
    hints_timeout_s: float | None = None   # None = read from settings (vision_portion_hints_timeout_ms)
    self_consistency_k: int | None = None  # None = read from settings (vision_self_consistency_k)
    hint_source: PortionHintSource | None = None  # None = skip catalog hints

    async def __call__(self, *, ctx: RecognitionContext) -> RecognitionOutcome:
        # Call 1 — identify
        identifications, identify_sha = await self.identifier.identify(
            image_bytes=ctx.image_bytes,
            mime=ctx.mime,
            user_id=ctx.user_id,
            locale=ctx.locale,
            region=ctx.region,
            meal_time=ctx.meal_time,
            plan_context=ctx.plan_context,
            user_context=ctx.user_context,
            model=ctx.model_override,
        )

        if not identifications:
            log.warning("vision.identify.empty", user_id=str(ctx.user_id))
            return RecognitionOutcome(
                items=(),
                prompt_sha256=f"{identify_sha}:",
                identification_conf_avg=0.0,
                estimation_conf_avg=0.0,
                degraded=True,
            )

        # Load portion hints (best-effort, bounded by timeout)
        hints: Mapping[int, PortionHint] = {}
        try:
            hints = await asyncio.wait_for(
                self._load_hints(identifications), timeout=self._get_hints_timeout_s()
            )
        except TimeoutError:
            log.warning("vision.hints.timeout", n_items=len(identifications))
        except Exception:  # noqa: BLE001 — hints are best-effort, never correctness dependency
            log.warning("vision.hints.error", n_items=len(identifications))

        # Call 2 — estimate grams (always runs, receives image + identifications + hints)
        degraded = False
        estimates: list[PortionEstimate] = []
        estimate_sha = ""
        try:
            k = self._get_k()
            if k >= 2:
                estimates, estimate_sha = await self._estimate_with_consistency(
                    ctx=ctx,
                    identifications=identifications,
                    hints=hints,
                    k=k,
                )
            else:
                estimates, estimate_sha = await self.estimator.estimate(
                    image_bytes=ctx.image_bytes,
                    mime=ctx.mime,
                    identifications=identifications,
                    portion_hints=hints or None,
                    user_id=ctx.user_id,
                    locale=ctx.locale,
                    region=ctx.region,
                    meal_time=ctx.meal_time,
                    user_profile=ctx.user_profile,
                    portion_history=ctx.portion_history,
                    user_context=ctx.user_context,
                    model=ctx.model_override,
                )
        except CostCapExceeded:
            raise  # propagate — user hit daily cap, not an upstream failure
        except Exception:  # noqa: BLE001 — upstream failure, degrade gracefully
            log.exception("vision.estimate.failed", n_items=len(identifications))
            degraded = True

        id_conf_avg = sum(i.confidence for i in identifications) / len(identifications)

        if degraded or not estimates:
            items = self._degrade(identifications)
            return RecognitionOutcome(
                items=tuple(items),
                prompt_sha256=f"{identify_sha}:{estimate_sha}",
                identification_conf_avg=id_conf_avg,
                estimation_conf_avg=0.0,
                degraded=True,
            )

        # Filter out-of-range indices — they are LLM hallucinations that would
        # corrupt estimation_conf_avg and are silently dropped by _merge anyway.
        n_ids = len(identifications)
        in_range: list[PortionEstimate] = []
        for e in estimates:
            if e.index >= n_ids:
                log.warning("vision.estimate.index_out_of_range", index=e.index, n_items=n_ids)
            else:
                in_range.append(e)

        # Align estimates to identifications by index; first occurrence wins on
        # duplicate indices (a 900 g hallucination must not overwrite 100 g).
        seen_indices: set[int] = set()
        estimate_map: dict[int, PortionEstimate] = {}
        for e in in_range:
            if e.index in seen_indices:
                log.warning("vision.estimate.duplicate_index", index=e.index)
                continue  # first-wins: preserve the first valid estimate
            seen_indices.add(e.index)
            estimate_map[e.index] = e

        merged = self._merge(identifications, estimate_map)
        # Compute confidence from unique, in-range estimates only.
        est_conf_avg = (
            sum(e.confidence for e in estimate_map.values()) / len(estimate_map)
            if estimate_map else 0.0
        )

        return RecognitionOutcome(
            items=tuple(merged),
            prompt_sha256=f"{identify_sha}:{estimate_sha}",
            identification_conf_avg=id_conf_avg,
            estimation_conf_avg=est_conf_avg,
            degraded=False,
        )

    def _get_k(self) -> int:
        """Return the self-consistency K value, falling back to settings when not injected."""
        if self.self_consistency_k is not None:
            return self.self_consistency_k
        return get_settings().vision_self_consistency_k

    def _get_hints_timeout_s(self) -> float:
        """Return the hints timeout in seconds, falling back to settings when not injected."""
        if self.hints_timeout_s is not None:
            return self.hints_timeout_s
        return get_settings().vision_portion_hints_timeout_ms / 1000.0

    async def _estimate_with_consistency(
        self,
        *,
        ctx: RecognitionContext,
        identifications: Sequence[FoodIdentification],
        hints: Mapping[int, PortionHint],
        k: int,
    ) -> tuple[list[PortionEstimate], str]:
        """K concurrent estimate calls → per-item median aggregation.

        Failure tolerance: if < ceil(K/2) calls fail, the successful runs are
        used for aggregation.  If >= ceil(K/2) fail the first exception is
        re-raised so the outer degradation path fires.

        SHA: sha256(sha_run_0 + sha_run_1 + ... + sha_run_{k-1}) where each
        failed run contributes an empty string.  This makes the composite SHA
        sensitive to both the per-call prompt content and the value of K.
        """
        tasks = [
            self.estimator.estimate(
                image_bytes=ctx.image_bytes,
                mime=ctx.mime,
                identifications=identifications,
                portion_hints=hints or None,
                user_id=ctx.user_id,
                locale=ctx.locale,
                region=ctx.region,
                meal_time=ctx.meal_time,
                user_profile=ctx.user_profile,
                portion_history=ctx.portion_history,
                user_context=ctx.user_context,
                model=ctx.model_override,
            )
            for _ in range(k)
        ]
        raw_results: list[object] = await asyncio.gather(*tasks, return_exceptions=True)

        # Partition successes vs failures (preserve positional order for SHA).
        successes: list[tuple[list[PortionEstimate], str]] = []
        failures: list[BaseException] = []
        for r in raw_results:
            if isinstance(r, BaseException):
                failures.append(r)
            else:
                successes.append(r)  # type: ignore[arg-type]

        fail_threshold = math.ceil(k / 2)
        if len(failures) >= fail_threshold:
            log.warning(
                "vision.self_consistency.majority_failed",
                k=k,
                n_failed=len(failures),
                fail_threshold=fail_threshold,
            )
            raise failures[0]

        if failures:
            log.info(
                "vision.self_consistency.minority_failed",
                k=k,
                n_failed=len(failures),
                n_succeeded=len(successes),
            )

        # Compose SHA from all K positional slots (failed → empty string).
        success_iter = iter(successes)
        all_shas: list[str] = [
            "" if isinstance(r, BaseException) else next(success_iter)[1]
            for r in raw_results
        ]
        composite_sha = hashlib.sha256("".join(all_shas).encode()).hexdigest()

        # Collect per-index estimates from all successful runs.
        index_estimates: dict[int, list[PortionEstimate]] = {}
        for estimates_list, _ in successes:
            for est in estimates_list:
                index_estimates.setdefault(est.index, []).append(est)

        # Aggregate: median grams, macros from closest run, mean confidence.
        merged: list[PortionEstimate] = []
        for idx in sorted(index_estimates.keys()):
            run_estimates = index_estimates[idx]
            amounts = [e.estimated_amount_g for e in run_estimates]
            median_amount = _median_decimal(amounts)

            # Pick the run whose amount is closest to the median → use its macros.
            best_est = min(
                run_estimates,
                key=lambda e: abs(e.estimated_amount_g - median_amount),
            )

            # Recompute kcal with Atwater so it is coherent with the chosen macros.
            atwater_kcal = best_est.protein_g * 4 + best_est.carbs_g * 4 + best_est.fat_g * 9
            final_kcal = atwater_kcal if atwater_kcal > 0 else best_est.kcal

            mean_conf = sum(e.confidence for e in run_estimates) / len(run_estimates)
            mean_conf = min(1.0, max(0.0, mean_conf))

            merged.append(
                PortionEstimate(
                    index=idx,
                    estimated_amount_g=median_amount,
                    kcal=final_kcal,
                    protein_g=best_est.protein_g,
                    carbs_g=best_est.carbs_g,
                    fat_g=best_est.fat_g,
                    confidence=mean_conf,
                )
            )

        log.info(
            "vision.self_consistency.done",
            k=k,
            n_succeeded=len(successes),
            n_items=len(merged),
        )
        return merged, composite_sha

    async def _load_hints(
        self, ids: Sequence[FoodIdentification]
    ) -> Mapping[int, PortionHint]:
        if self.hint_source is None:
            return {}
        names = [ident.name for ident in ids]
        name_to_hint = await self.hint_source.load_hints(names)
        if not name_to_hint:
            return {}
        return {i: name_to_hint[ident.name] for i, ident in enumerate(ids) if ident.name in name_to_hint}

    @staticmethod
    def _merge(
        ids: Sequence[FoodIdentification],
        estimate_map: Mapping[int, PortionEstimate],
    ) -> list[DetectedFoodItem]:
        """Merge identification + estimation by index. Missing estimate → degrade that item."""
        items: list[DetectedFoodItem] = []
        for i, ident in enumerate(ids):
            est = estimate_map.get(i)
            if est is None:
                # Individual item degraded
                items.append(
                    DetectedFoodItem(
                        name=ident.name,
                        food_group=ident.group,
                        estimated_amount_g=Decimal("100"),
                        kcal=0,
                        protein_g=0,
                        carbs_g=0,
                        fat_g=0,
                        confidence=0.2,
                        role=ident.role,
                        prep_method=ident.prep_method,
                        count=ident.count,
                        inferred=ident.inferred,
                        bbox=ident.bbox,
                    )
                )
            else:
                items.append(
                    DetectedFoodItem(
                        name=ident.name,
                        food_group=ident.group,
                        estimated_amount_g=est.estimated_amount_g,
                        kcal=est.kcal,
                        protein_g=est.protein_g,
                        carbs_g=est.carbs_g,
                        fat_g=est.fat_g,
                        confidence=min(ident.confidence, est.confidence),
                        role=ident.role,
                        prep_method=ident.prep_method,
                        count=ident.count,
                        inferred=ident.inferred,
                        bbox=ident.bbox,
                    )
                )
        return items

    @staticmethod
    def _degrade(ids: Sequence[FoodIdentification]) -> list[DetectedFoodItem]:
        """Call 2 upstream failure: catalog median grams, confidence forced low."""
        return [
            DetectedFoodItem(
                name=ident.name,
                food_group=ident.group,
                estimated_amount_g=Decimal("100"),
                kcal=0,
                protein_g=0,
                carbs_g=0,
                fat_g=0,
                confidence=0.25,  # Forces escalation in process_vision_job
                role=ident.role,
                prep_method=ident.prep_method,
                count=ident.count,
                inferred=ident.inferred,
                bbox=ident.bbox,
            )
            for ident in ids
        ]
