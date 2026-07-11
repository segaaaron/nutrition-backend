"""Condition gates — Strategy + Registry per master plan H2.

Each gate implements the `ConditionGate` Protocol declared in `ports.py` and
contributes SQL filter fragments to Layer 1 eligibility. Registry pattern keeps
Layer1 free of growing if-chains as we unlock more conditions.
"""

from __future__ import annotations

from app.plan.domain.condition_gates.fatty_liver import FattyLiverGate
from app.plan.domain.condition_gates.lactation import LactationGate
from app.plan.domain.condition_gates.pregnancy import PregnancyGate
from app.plan.domain.condition_gates.registry import (
    CONDITION_GATES,
    gates_for,
    register_gate,
)

# Auto-register the in-scope gates at import time.
#
# Scope (owner decision 2026-07-09, enforced at the API boundary in
# `app/profile/presentation/schemas.py::MobileCondition`): NOVA is a general
# LATAM nutrition app, not a medical tool. Only one nutrition-managed
# situation (fatty_liver) plus two life stages (pregnancy, lactation) are
# accepted. Out-of-scope medical conditions (diabetes, hypertension,
# dyslipidemia, hypercholesterolemia, CKD, gout, ischemic heart disease) and
# the allergen-handled ones (celiac → gluten allergen, lactose intolerance →
# dairy allergen) were removed 2026-07-10 — their gates no longer exist so
# they cannot fire even if a stale condition string reaches Layer 1.
register_gate(LactationGate())
register_gate(PregnancyGate())
register_gate(FattyLiverGate())

__all__ = [
    "CONDITION_GATES",
    "register_gate",
    "gates_for",
    "LactationGate",
    "PregnancyGate",
    "FattyLiverGate",
]
