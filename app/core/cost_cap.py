"""OpenAI cost-cap middleware (ADR-0004).

Tracks per-user and per-org daily spend in Redis. Two keyed counters:

    oac:user:{user_id}:{YYYY-MM-DD}   (float USD, TTL = end of UTC day + 1h)
    oac:org:{date}                    (float USD)

API:
    estimate_input_cost(model, input_text) → USD via tiktoken token count
    pre_check(user_id, estimate_usd)       → raises CostCapExceeded or sets
                                              X-Cost-Limit-Warning hint
    record_usage(user_id, model, in_tok, out_tok)
                                            → updates both counters atomically

Soft cap warning at 80% of the per-user limit; hard cap returns 429. Kill
switch (`feature_flags.openai_kill_switch.enabled`) short-circuits before
any check. Pricing table is conservative — overestimates by ~10% vs the
public OpenAI prices so we never undercount.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Final
from uuid import UUID

from prometheus_client import Counter

from app.core.config import get_settings
from app.core.errors import CostCapExceeded
from app.core.logging import get_logger
from app.core.redis import get_redis

log = get_logger("cost_cap")

# USD per 1M tokens. Conservative (10% above published list).
_PRICING_PER_M: Final[dict[str, tuple[float, float]]] = {
    # model -> (input_per_1m, output_per_1m)
    "gpt-4o-mini": (0.17, 0.66),
    "gpt-4o-2024-08-06": (2.75, 11.00),
    "gpt-4o": (2.75, 11.00),
    "text-embedding-3-large": (0.143, 0.0),
}

_tokens_in = Counter(
    "openai_tokens_total",
    "Total OpenAI tokens consumed",
    ["model", "kind"],
)
_cost_usd = Counter(
    "openai_cost_usd_total",
    "Total OpenAI cost in USD",
    ["model", "user_segment"],
)


def _today_utc() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d")


def _price(model: str, in_tok: int, out_tok: int) -> float:
    pin, pout = _PRICING_PER_M.get(model, (5.0, 15.0))  # safe default
    return (in_tok / 1_000_000.0) * pin + (out_tok / 1_000_000.0) * pout


def _price_input(model: str) -> Decimal:
    """Return per-1M USD input price for the given model as Decimal.

    Used by cost-cap pre-checks that need to estimate image-token cost at
    the *actual* model rate (gpt-4o-mini = $0.17/1M vs gpt-4o = $2.75/1M).
    Falls back to the table's safe default if the model is unknown.
    CLAUDE.md non-negotiable #2: Decimal for cost math.
    """
    pin, _ = _PRICING_PER_M.get(model, (5.0, 15.0))
    return Decimal(str(pin))


def _price_output(model: str) -> Decimal:
    """Return per-1M USD output price for the given model as Decimal."""
    _, pout = _PRICING_PER_M.get(model, (5.0, 15.0))
    return Decimal(str(pout))


def estimate_input_cost(model: str, text: str) -> float:
    """Token-count via tiktoken; falls back to chars/4 if tokeniser is missing."""
    try:
        import tiktoken  # local import to avoid hard dep at import time

        if model in tiktoken.model.MODEL_TO_ENCODING:
            enc = tiktoken.encoding_for_model(model)
        else:
            enc = tiktoken.get_encoding("cl100k_base")
        n = len(enc.encode(text))
    except Exception:  # noqa: BLE001
        n = max(1, len(text) // 4)
    return _price(model, n, 0)


@dataclass(slots=True)
class CostCapDecision:
    allowed: bool
    warning: bool
    spent_usd: float
    cap_usd: float


async def kill_switch_active() -> bool:
    r = get_redis()
    val = await r.get("ff:openai_kill_switch")
    return bool(val == "1")


async def pre_check(*, user_id: UUID | None, estimate_usd: float) -> CostCapDecision:
    """Raises CostCapExceeded if user/org cap would be breached; otherwise
    returns a decision flagging warning if we crossed the soft threshold.

    Perf: batches the kill-switch GET, optional user-spent GET, and org-spent
    GET into a single Redis pipeline RTT (was 3 sequential awaits).
    """
    s = get_settings()
    r = get_redis()
    user_cap = s.cost_cap_usd_per_user_per_day
    org_cap = s.cost_cap_usd_per_org_per_day
    alarm = s.cost_cap_alarm_pct

    day = _today_utc()
    user_key = f"oac:user:{user_id}:{day}" if user_id else None
    org_key = f"oac:org:{day}"

    # Single-RTT batched GETs: [kill_switch, (user_spent?), org_spent].
    pipe = r.pipeline()
    pipe.get("ff:openai_kill_switch")
    if user_key:
        pipe.get(user_key)
    pipe.get(org_key)
    results = await pipe.execute()

    kill_val = results[0]
    if kill_val == "1":
        raise CostCapExceeded("kill_switch_active", reset_at="manual")

    idx = 1
    if user_key:
        user_spent = float(results[idx] or 0.0)
        idx += 1
    else:
        user_spent = 0.0
    org_spent = float(results[idx] or 0.0)

    if user_key and (user_spent + estimate_usd) > user_cap:
        raise CostCapExceeded(
            "user_cost_cap_exceeded",
            limit_usd=user_cap,
            spent_usd=user_spent,
            reset_at=f"{day}T24:00Z",
        )
    if (org_spent + estimate_usd) > org_cap:
        raise CostCapExceeded(
            "org_cost_cap_exceeded",
            limit_usd=org_cap,
            spent_usd=org_spent,
            reset_at=f"{day}T24:00Z",
        )
    warn = user_key is not None and (user_spent + estimate_usd) > alarm * user_cap
    return CostCapDecision(
        allowed=True,
        warning=warn,
        spent_usd=user_spent,
        cap_usd=user_cap,
    )


async def record_usage(
    *,
    user_id: UUID | None,
    model: str,
    in_tok: int,
    out_tok: int,
    user_segment: str = "free",
) -> float:
    cost = _price(model, in_tok, out_tok)
    r = get_redis()
    day = _today_utc()
    pipe = r.pipeline()
    if user_id is not None:
        ukey = f"oac:user:{user_id}:{day}"
        pipe.incrbyfloat(ukey, cost)
        pipe.expire(ukey, 36 * 3600)  # day + 12h buffer
    okey = f"oac:org:{day}"
    pipe.incrbyfloat(okey, cost)
    pipe.expire(okey, 36 * 3600)
    await pipe.execute()
    _tokens_in.labels(model=model, kind="input").inc(in_tok)
    _tokens_in.labels(model=model, kind="output").inc(out_tok)
    _cost_usd.labels(model=model, user_segment=user_segment).inc(cost)
    return cost
