"""Condition gates — Strategy + Registry per master plan H2.

Each gate implements the `ConditionGate` Protocol declared in `ports.py` and
contributes SQL filter fragments to Layer 1 eligibility. Registry pattern keeps
Layer1 free of growing if-chains as we unlock more conditions.
"""

from __future__ import annotations

from app.plan.domain.condition_gates.celiac import CeliacGate
from app.plan.domain.condition_gates.ckd import CKDGate
from app.plan.domain.condition_gates.diabetes_t1 import DiabetesT1Gate
from app.plan.domain.condition_gates.diabetes_t2 import DiabetesT2Gate
from app.plan.domain.condition_gates.dyslipidemia import DyslipidemiaGate
from app.plan.domain.condition_gates.fatty_liver import FattyLiverGate
from app.plan.domain.condition_gates.gout import GoutGate
from app.plan.domain.condition_gates.hypercholesterolemia import HypercholesterolemiaGate
from app.plan.domain.condition_gates.hypertension import HypertensionGate
from app.plan.domain.condition_gates.ischemic_heart_disease import IschemicHeartDiseaseGate
from app.plan.domain.condition_gates.lactation import LactationGate
from app.plan.domain.condition_gates.lactose_intolerance import LactoseIntoleranceGate
from app.plan.domain.condition_gates.pregnancy import PregnancyGate
from app.plan.domain.condition_gates.registry import (
    CONDITION_GATES,
    gates_for,
    register_gate,
)

# Auto-register all gates at import time.
register_gate(LactationGate())
register_gate(PregnancyGate())
register_gate(DiabetesT1Gate())
register_gate(DiabetesT2Gate())
register_gate(CKDGate())
register_gate(HypertensionGate())
register_gate(HypercholesterolemiaGate())
register_gate(DyslipidemiaGate())
register_gate(GoutGate())
register_gate(CeliacGate())
register_gate(LactoseIntoleranceGate())
register_gate(FattyLiverGate())
register_gate(IschemicHeartDiseaseGate())

__all__ = [
    "CONDITION_GATES",
    "register_gate",
    "gates_for",
    "LactationGate",
    "PregnancyGate",
    "DiabetesT1Gate",
    "DiabetesT2Gate",
    "CKDGate",
    "HypertensionGate",
    "HypercholesterolemiaGate",
    "DyslipidemiaGate",
    "GoutGate",
    "CeliacGate",
    "LactoseIntoleranceGate",
    "FattyLiverGate",
    "IschemicHeartDiseaseGate",
]
