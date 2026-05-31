"""Layer 4 — coherence orchestration wrapper.

Thin adapter that delegates to the OpenAI client. Lives in `application` so
the use case can swap implementations (e.g., a no-op stub in tests).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID


class _CoherenceClient(Protocol):
    async def __call__(
        self,
        *,
        user_profile: dict,
        candidate_plan: list[dict],
        alternatives_by_slot: dict[tuple[int, str], list[str]],
    ) -> dict: ...


@dataclass(slots=True)
class Layer4Coherence:
    client: _CoherenceClient

    async def __call__(
        self,
        *,
        user_id: UUID,
        user_profile: dict,
        candidate_plan: list[dict],
        alternatives_by_slot: dict[tuple[int, str], list[str]],
    ) -> dict:
        return await self.client(
            user_profile=user_profile,
            candidate_plan=candidate_plan,
            alternatives_by_slot=alternatives_by_slot,
        )
