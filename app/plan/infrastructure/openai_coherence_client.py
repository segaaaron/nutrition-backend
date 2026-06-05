"""Layer 4 — OpenAI gpt-4o-mini coherence pass.

Single call per plan generation (not per recipe). Strict JSON schema output
constrains the response shape; we validate post-decode that every swap
points to a candidate from the supplied alternatives map. Cached in Redis
for 24h keyed by `(user_profile_hash, candidate_set_hash)` because the
expensive bit is the LLM call — the underlying plan is deterministic given
those two hashes.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from openai import AsyncOpenAI

from app.core.circuit_breaker import CircuitBreaker
from app.core.config import get_settings
from app.core.cost_cap import estimate_input_cost, pre_check, record_usage
from app.core.logging import get_logger
from app.core.redis import get_redis

log = get_logger("plan.coherence")

_client: AsyncOpenAI | None = None
_breaker = CircuitBreaker(name="openai_coherence", fail_threshold=3, recovery_timeout_s=30)

CACHE_TTL_S = 24 * 3600
COST_HARD_CAP_USD = 0.02


_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "ok": {"type": "boolean"},
        "swaps": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "day": {"type": "integer"},
                    "meal_time": {"type": "string"},
                    "replace_recipe_id": {"type": "string"},
                    "new_recipe_id": {"type": "string"},
                    "reason": {"type": "string"},
                },
                "required": ["day", "meal_time", "replace_recipe_id", "new_recipe_id", "reason"],
            },
        },
        "why_paragraph": {"type": "string"},
    },
    "required": ["ok", "swaps", "why_paragraph"],
}


def _get_client() -> AsyncOpenAI:
    global _client  # noqa: PLW0603 — lazy module-level singleton, intentional
    if _client is None:
        _client = AsyncOpenAI(api_key=get_settings().openai_api_key or "sk-test")
    return _client


def _hash_inputs(user_profile: dict, candidate_plan: list[dict]) -> str:
    raw = json.dumps([user_profile, candidate_plan], sort_keys=True).encode()
    return hashlib.sha256(raw).hexdigest()


@dataclass(slots=True)
class CoherencePass:
    user_id: UUID | None
    model: str | None = None

    def _model(self) -> str:
        return self.model or get_settings().openai_chat_model

    async def __call__(
        self,
        *,
        user_profile: dict,
        candidate_plan: list[dict],
        alternatives_by_slot: dict[tuple[int, str], list[str]],
    ) -> dict:
        """Returns the validated coherence response dict.

        On any error (cache miss + LLM failure / circuit open / cost cap),
        returns a safe no-op `{ok: True, swaps: [], why_paragraph: ""}` so
        plan generation never blocks on the LLM.
        """
        redis = get_redis()
        cache_key = "plan:coh:" + _hash_inputs(user_profile, candidate_plan)
        cached = await redis.get(cache_key)
        if cached:
            try:
                return json.loads(cached)
            except Exception:  # noqa: BLE001,S110 — cache miss falls through to rebuild
                pass

        prompt = self._prompt(user_profile, candidate_plan, alternatives_by_slot)
        model = self._model()
        est = estimate_input_cost(model, prompt)
        if est > COST_HARD_CAP_USD:
            log.warning("plan.coherence.skip_cost", est_usd=est)
            return {"ok": True, "swaps": [], "why_paragraph": ""}

        try:
            await pre_check(user_id=self.user_id, estimate_usd=est)
        except Exception as exc:  # noqa: BLE001
            log.warning("plan.coherence.cap_blocked", error=str(exc))
            return {"ok": True, "swaps": [], "why_paragraph": ""}

        async def _do_call() -> dict:
            resp = await _get_client().chat.completions.create(
                model=model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are a registered dietitian validating a meal plan for "
                            "macro/micro balance, repetition, and cultural coherence. "
                            "Suggest at most 3 swaps and choose only from the provided "
                            "alternatives map. Output strict JSON conforming to the schema."
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "name": "plan_coherence",
                        "strict": True,
                        "schema": _SCHEMA,
                    },
                },
                temperature=0.2,
            )
            content = resp.choices[0].message.content or "{}"
            usage = resp.usage
            await record_usage(
                user_id=self.user_id,
                model=model,
                in_tok=getattr(usage, "prompt_tokens", 0) if usage else 0,
                out_tok=getattr(usage, "completion_tokens", 0) if usage else 0,
            )
            return json.loads(content)

        try:
            raw = await _breaker.call(_do_call)
        except Exception as exc:  # noqa: BLE001
            log.warning("plan.coherence.upstream_failed", error=str(exc))
            return {"ok": True, "swaps": [], "why_paragraph": ""}

        validated = self._validate_swaps(raw, alternatives_by_slot)
        await redis.set(cache_key, json.dumps(validated), ex=CACHE_TTL_S)
        return validated

    def _prompt(
        self,
        user_profile: dict,
        candidate_plan: list[dict],
        alternatives: dict[tuple[int, str], list[str]],
    ) -> str:
        return json.dumps(
            {
                "user_profile": user_profile,
                "plan": candidate_plan,
                "alternatives": {f"{d}|{mt}": ids for (d, mt), ids in alternatives.items()},
            },
            sort_keys=True,
        )

    @staticmethod
    def _validate_swaps(
        raw: dict,
        alternatives: dict[tuple[int, str], list[str]],
    ) -> dict:
        out_swaps: list[dict] = []
        for swap in raw.get("swaps", []) or []:
            try:
                day = int(swap.get("day", 0))
                meal_time = str(swap.get("meal_time", ""))
                new_id = str(swap.get("new_recipe_id", ""))
                allowed = {str(x) for x in alternatives.get((day, meal_time), [])}
                if new_id in allowed:
                    out_swaps.append(swap)
            except Exception:  # noqa: BLE001, S112 — defensive: skip malformed swap entries from LLM
                continue
        return {
            "ok": bool(raw.get("ok", True)),
            "swaps": out_swaps[:3],
            "why_paragraph": str(raw.get("why_paragraph", ""))[:1500],
        }
