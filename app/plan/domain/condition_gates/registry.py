"""Condition gate registry — Strategy pattern (master plan H2).

`register_gate(gate)` adds a gate to the registry. `gates_for(condition)`
returns the list of gates registered for that condition. Layer 1 eligibility
calls `gates_for(user_condition)` for each user condition and concatenates
SQL fragment contributions.

Threadsafe: registry only mutated at module import time (auto-register in
`__init__.py`). Runtime access is read-only.
"""
from __future__ import annotations

from typing import Protocol

# Forward-declare the gate shape locally to avoid importing ports.py
# (which depends on context.py — keeps registry import-light). Read-only
# property satisfies frozen dataclasses' attribute access without forcing
# settable semantics.
class _GateLike(Protocol):
    @property
    def condition(self) -> str: ...


CONDITION_GATES: dict[str, list[_GateLike]] = {}


def register_gate(gate: _GateLike) -> None:
    """Append `gate` to the registry under its declared condition."""
    CONDITION_GATES.setdefault(gate.condition, []).append(gate)


def gates_for(condition: str) -> list[_GateLike]:
    """Return registered gates for `condition` (empty list if none)."""
    return CONDITION_GATES.get(condition, [])
