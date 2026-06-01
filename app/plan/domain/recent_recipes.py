"""Port for reading a user's recent recipe / tag / ingredient-class history.

Used by variety-oriented ranking signals to penalize candidates that are
too similar to what the user has eaten in the last N days.

Concrete implementations live in the tracking bounded context (or its
infrastructure layer). The domain only declares the contract.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable
from uuid import UUID


@runtime_checkable
class RecentRecipesReader(Protocol):
    """Read-only port over a user's recent eating history.

    All methods return immutable `frozenset` projections so that signal
    implementations cannot mutate shared state.
    """

    async def tags_used_14d(self, user_id: UUID) -> frozenset[str]: ...

    async def ingredient_classes_used_14d(
        self, user_id: UUID
    ) -> frozenset[str]: ...

    async def recipe_ids_used_7d(self, user_id: UUID) -> frozenset[UUID]: ...
