"""Constraint registry — Strategy pattern (mirror of condition_gates/registry).

`register_constraint(c)` adds a constraint by name. `all_constraints()` returns
the registered list. Layer 4 coherence iterates over the registry to collect
violations against a DraftPlan.

Threadsafe: only mutated at module import time (auto-register in __init__.py).
Runtime access is read-only.
"""

from __future__ import annotations

from typing import Protocol

from app.plan.domain.context import DraftPlan, Violation


class _ConstraintLike(Protocol):
    @property
    def name(self) -> str: ...

    def check(self, plan: DraftPlan) -> list[Violation]: ...


CONSTRAINTS: dict[str, _ConstraintLike] = {}


def register_constraint(c: _ConstraintLike) -> None:
    """Register `c` under its declared `name`. Last write wins on collision."""
    CONSTRAINTS[c.name] = c


def all_constraints() -> list[_ConstraintLike]:
    """Return all registered constraints in insertion order."""
    return list(CONSTRAINTS.values())
