"""Recipes domain events."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from app.core.event_bus import DomainEvent


@dataclass(frozen=True, slots=True)
class RecipeCreated(DomainEvent):
    recipe_id: UUID
    at: datetime


@dataclass(frozen=True, slots=True)
class RecipeSearched(DomainEvent):
    user_id: UUID | None
    query_hash: str
    n_results: int
    at: datetime
