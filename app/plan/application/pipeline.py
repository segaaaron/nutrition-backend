"""Plan-generation pipeline runner.

Sequentially applies a list of Stages over an immutable PlanGenContext,
threading a budget and emitting a StageTrace for each stage.

Zero business logic lives here - this module only orchestrates Stage
implementations declared in the domain layer.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Sequence

from app.core.logging import get_logger
from app.plan.domain.context import PlanGenContext, StageTrace
from app.plan.domain.ports import Stage

log = get_logger("plan.pipeline")


class StageBudgetExceeded(Exception):
    """Raised when the pipeline's remaining time budget is exhausted."""

    def __init__(self, stage_name: str, budget_remaining_ms: int) -> None:
        super().__init__(
            f"stage_budget_exceeded:{stage_name}:remaining={budget_remaining_ms}ms"
        )
        self.stage_name = stage_name
        self.budget_remaining_ms = budget_remaining_ms


@dataclass(slots=True)
class Pipeline:
    """Sequential Stage runner with per-stage timing + audit trail."""

    stages: Sequence[Stage]

    async def run(self, ctx: PlanGenContext) -> PlanGenContext:
        for stage in self.stages:
            if ctx.budget_ms_remaining <= 0:
                raise StageBudgetExceeded(stage.name, ctx.budget_ms_remaining)
            t0 = time.perf_counter_ns()
            input_count = (
                sum(len(v) for v in ctx.candidates_by_slot.values())
                if ctx.candidates_by_slot
                else 0
            )
            ctx = await stage.apply(ctx)
            duration_ms = (time.perf_counter_ns() - t0) // 1_000_000
            output_count = (
                sum(len(v) for v in ctx.candidates_by_slot.values())
                if ctx.candidates_by_slot
                else len(ctx.selected)
            )
            trace = StageTrace(
                stage_name=stage.name,
                duration_ms=int(duration_ms),
                input_candidates=input_count,
                output_candidates=output_count,
            )
            ctx = ctx.with_stage_trace(trace)
            log.info(
                "plan_stage",
                stage=stage.name,
                duration_ms=duration_ms,
                in_=input_count,
                out=output_count,
            )
        return ctx
