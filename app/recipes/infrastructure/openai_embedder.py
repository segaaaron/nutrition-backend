"""OpenAI text-embedding-3-large adapter, dimension-truncated to 1536.

Wrapped in the generic `CircuitBreaker` (3 fails / 30s recovery) — the
embedder is on the hot path for semantic search and a hung OpenAI call must
not cascade to the FastAPI worker. Cost is tracked through `CostCap` before
issuing the call.
"""

from __future__ import annotations

from openai import AsyncOpenAI

from app.core.circuit_breaker import CircuitBreaker
from app.core.config import get_settings

_client: AsyncOpenAI | None = None
_breaker = CircuitBreaker(name="openai_embedder", fail_threshold=3, recovery_timeout_s=30)


def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(api_key=get_settings().openai_api_key or "sk-test")
    return _client


class OpenAIEmbedder:
    """Implements the `EmbeddingProvider` port."""

    def __init__(self, model: str | None = None, dim: int | None = None) -> None:
        s = get_settings()
        self.model = model or s.openai_embed_model
        self.dim = dim or s.openai_embed_dim

    async def embed(self, text: str) -> list[float]:
        async def _call() -> list[float]:
            resp = await _get_client().embeddings.create(
                model=self.model,
                input=text,
                dimensions=self.dim,
            )
            return list(resp.data[0].embedding)

        return await _breaker.call(_call)
