"""OpenAI whisper-1 STT adapter.

Cost: $0.006/minute audio. Cost cap pre-check uses a duration estimate
(seconds / 60 * 0.006). Circuit breaker shared name "openai_whisper"
(3 fails / 30s). Max audio: 1MB, max 60s — enforced upstream in the router.
"""
from __future__ import annotations

import io
from dataclasses import dataclass
from uuid import UUID

from openai import AsyncOpenAI

from app.core.circuit_breaker import CircuitBreaker
from app.core.config import get_settings
from app.core.cost_cap import pre_check, record_usage
from app.core.errors import UpstreamError
from app.core.logging import get_logger

log = get_logger("voice.whisper")

_client: AsyncOpenAI | None = None
_breaker = CircuitBreaker(name="openai_whisper", fail_threshold=3, recovery_timeout_s=30)


def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(api_key=get_settings().openai_api_key or "sk-test", timeout=30.0)
    return _client


@dataclass(slots=True)
class WhisperClient:
    model: str = "whisper-1"

    async def transcribe(
        self,
        *,
        audio_bytes: bytes,
        mime: str,
        duration_s: float,
        user_id: UUID | None,
        locale: str = "es",
    ) -> str:
        # Estimate cost up front.
        est_usd = max(0.001, (duration_s / 60.0) * 0.006)
        await pre_check(user_id=user_id, estimate_usd=est_usd)

        async def _call() -> str:
            buf = io.BytesIO(audio_bytes)
            # OpenAI SDK requires file-like with a name attribute.
            buf.name = "audio." + (mime.split("/")[-1] if "/" in mime else "m4a")
            resp = await _get_client().audio.transcriptions.create(
                model=self.model, file=buf, language=locale[:2],
                response_format="text",
            )
            # Record usage — whisper has only "input minutes" so we encode
            # `in_tok` as ceil(seconds) for accounting tractability.
            await record_usage(
                user_id=user_id, model=self.model,
                in_tok=int(duration_s),  # 1 token = 1 second for whisper-1
                out_tok=0,
            )
            return resp if isinstance(resp, str) else getattr(resp, "text", "")

        try:
            return await _breaker.call(_call)
        except Exception as exc:  # noqa: BLE001
            log.warning("voice.whisper.failed", err=str(exc))
            raise UpstreamError(f"whisper_failed:{exc!s}")
