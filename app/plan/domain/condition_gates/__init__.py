"""Condition gates — Strategy + Registry per master plan H2.

Each gate implements the `ConditionGate` Protocol declared in `ports.py` and
contributes SQL filter fragments to Layer 1 eligibility. Registry pattern keeps
Layer1 free of growing if-chains as we unlock more clinical conditions.
"""
from __future__ import annotations

from app.plan.domain.condition_gates.celiac import CeliacGate
from app.plan.domain.condition_gates.ckd import CKDGate
from app.plan.domain.condition_gates.diabetes_t2 import DiabetesT2Gate
from app.plan.domain.condition_gates.hypertension import HypertensionGate
from app.plan.domain.condition_gates.lactation import LactationGate
from app.plan.domain.condition_gates.pregnancy import PregnancyGate
from app.plan.domain.condition_gates.registry import (
    CONDITION_GATES,
    register_gate,
    gates_for,
)

# Auto-register built-in gates at import time. Order does not matter — Layer 1
# composes all gates registered for a user's condition into a single WHERE
# clause via AND.
register_gate(LactationGate())
register_gate(PregnancyGate())
register_gate(DiabetesT2Gate())
register_gate(CKDGate())
register_gate(HypertensionGate())
register_gate(CeliacGate())

__all__ = [
    "CONDITION_GATES", "register_gate", "gates_for",
    "LactationGate", "PregnancyGate", "DiabetesT2Gate",
    "CKDGate", "HypertensionGate", "CeliacGate",
]
