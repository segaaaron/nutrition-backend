"""Plan-generation Constraints — Strategy + Registry per master plan §H1.

Each constraint implements the `Constraint` Protocol from
`app.plan.domain.ports` and reports zero-or-more `Violation`s against a
`DraftPlan`. Layer 4 coherence iterates the registry; the greedy solver swaps
slots to drive violations to zero.
"""
from __future__ import annotations

from app.plan.domain.constraints.liquid_cap import LiquidCap
from app.plan.domain.constraints.registry import (
    CONSTRAINTS,
    all_constraints,
    register_constraint,
)

# Auto-register built-in constraints at import time.
register_constraint(LiquidCap())

__all__ = [
    "CONSTRAINTS",
    "LiquidCap",
    "all_constraints",
    "register_constraint",
]
