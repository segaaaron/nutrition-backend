"""Coach value objects — Role, Intent enums + ContextWindow."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Role(str, Enum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


class Intent(str, Enum):
    # Templates (Camino 1, 40%)
    VIEW_TODAY_PLAN = "view_today_plan"
    NEXT_MEAL = "next_meal"
    STREAK_STATUS = "streak_status"
    WATER_PROGRESS = "water_progress"
    PROTEIN_REMAINING = "protein_remaining"
    MARK_WATER = "mark_water"
    # Mid (Camino 3 / 35%)
    SWAP_MEAL = "swap_meal"
    WHY_PLAN = "why_plan"
    IM_HUNGRY = "im_hungry"
    ALLERGY_UPDATE = "allergy_update"
    PLATEAU = "plateau"
    GENERAL = "general"
    # Refuse (Camino 4 / 5%)
    MEDICAL_REDIRECT = "medical_redirect"
    OFFTOPIC_REDIRECT = "offtopic_redirect"
    PROMPT_INJECTION = "prompt_injection"


@dataclass(slots=True)
class ContextWindow:
    """Compact grounded context (~600 tokens fixed budget)."""

    profile_compact: str = ""           # ~150 tokens
    active_plan_today: str = ""         # ~100 tokens
    last_food_logs: str = ""            # ~80 tokens
    rag_recipes: list[dict] = field(default_factory=list)  # ~400 tokens for top 5
    last_messages: list[dict] = field(default_factory=list)  # ~200 tokens, 4 msgs
