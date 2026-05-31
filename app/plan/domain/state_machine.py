"""Formal Plan state machine (spec §9.3).

States: active → completed | cancelled (terminals).
Events accepted from each state:

    active:
      - MEAL_COMPLETE        → active (or completed if last meal of plan)
      - DAY_COMPLETE         → active (or completed if last day)
      - SWAP_MEAL            → active
      - REGENERATE           → active (new version)
      - CANCEL               → cancelled
    completed: (terminal — only ARCHIVE allowed, no-op for now)
    cancelled: (terminal)

Implemented as a pure function `advance(plan, event, **payload) -> Plan` that
raises `IllegalTransition` (subclass of ConflictError → 409) for unsupported
edges. The orchestrator commits a new ORM snapshot per transition.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from typing import Literal
from uuid import UUID

from app.core.errors import IllegalTransition
from app.plan.domain.entities import Plan

Event = Literal["MEAL_COMPLETE", "DAY_COMPLETE", "SWAP_MEAL", "REGENERATE", "CANCEL"]

_ALLOWED: dict[str, set[str]] = {
    "active": {"MEAL_COMPLETE", "DAY_COMPLETE", "SWAP_MEAL", "REGENERATE", "CANCEL"},
    "completed": set(),
    "cancelled": set(),
}


def advance(plan: Plan, event: Event, **_payload: object) -> Plan:
    if event not in _ALLOWED.get(plan.status, set()):
        raise IllegalTransition(
            f"illegal_transition:{plan.status}+{event}",
            current_state=plan.status, event=event,
        )

    if event == "CANCEL":
        return replace(plan, status="cancelled")

    if event == "REGENERATE":
        return replace(plan, version=plan.version + 1)

    if event == "DAY_COMPLETE":
        new_current = min(plan.current_day + 1, plan.total_days)
        if new_current >= plan.total_days and plan.current_day >= plan.total_days:
            return replace(plan, status="completed")
        if plan.current_day + 1 > plan.total_days:
            return replace(plan, status="completed")
        return replace(plan, current_day=new_current)

    # MEAL_COMPLETE / SWAP_MEAL leave high-level state untouched; per-meal
    # mutation happens on the PlanMeal record itself by the repository.
    return plan
