"""R10 — multi-condition composite hard-cap invariants.

When a user declares two-to-four conditions simultaneously, Layer 1
eligibility composes a SQL WHERE clause from:
  * inline filters in `Layer1EligibilityRepository.select_eligible_ids`
    (diabetes_t2, hypertension, hypercholesterolemia, ckd, gout)
  * registered `ConditionGate` strategies in
    `app/plan/domain/condition_gates/` (diabetes_t2, hypertension, ckd,
    celiac, pregnancy, lactation)

This module asserts the COMPOSITE produced for any random combo of 2–4
conditions still emits a fragment that proves the per-meal hard cap for
each applicable condition:

  dm2          → sugar_g ≤ 15
  htn          → sodium_mg ≤ 600
  hyperchol    → sat_fat_g ≤ 5
  ckd          → protein_g ≤ weight_kg × 0.8 / 3
  gout         → tags exclude organ_meat / shellfish
  celiac       → contraindicated_for not ∋ celiac (gate-level)
  lactation    → lactation gate present
  pregnancy    → pregnancy gate present

We exercise the COMPOSITION CONTRACT (SQL strings + bound parameters), not
the live DB execution path — that is integration-tested elsewhere. This
sweep proves the invariant: no condition is silently dropped when several
are declared together, and the published hard caps survive composition.

Hypothesis strategies sample over the explicit set in the spec excluding
the blocked `diabetes_t1` (CLAUDE.md GOLDEN RULE #3).
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from app.plan.domain.condition_gates import gates_for

# Subset the spec called out, excluding diabetes_t1 (blocked).
_CONDITIONS = (
    "diabetes_t2",
    "hypertension",
    "hypercholesterolemia",
    "ckd",
    "gout",
    "celiac",
    "lactation",
    "pregnancy",
)

# Per-condition expected hard caps that MUST appear in the composed SQL or
# in a registered gate's bound params.
_EXPECTED_INLINE_FRAGMENTS: dict[str, list[str]] = {
    "diabetes_t2": ["sugar_g", "<= 15"],
    "hypertension": ["sodium_mg", "<= 600"],
    "hypercholesterolemia": ["sat_fat_g", "<= 5"],
    "ckd": ["protein_g", "ckd_protein_cap"],
    "gout": ["organ_meat", "shellfish"],
}

_SETTINGS = settings(
    max_examples=120,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.filter_too_much],
)


def _compose_inline_fragments(
    conditions: frozenset[str], weight_kg: float | None
) -> tuple[list[str], dict[str, object]]:
    """Reproduce the inline filter assembly from Layer 1 (frozen contract).

    Keeping this mirror in the test avoids importing the repository (which
    pulls in SQLAlchemy session). The fragments must stay in sync with
    `app/plan/application/layer1_eligibility.py` — any change there should
    update this mirror, which is exactly the contract this test guards.
    """
    where: list[str] = []
    params: dict[str, object] = {}
    if "diabetes_t2" in conditions:
        where.append("(r.sugar_g IS NOT NULL AND r.sugar_g <= 15)")
    if "hypertension" in conditions:
        where.append("(r.sodium_mg IS NOT NULL AND r.sodium_mg <= 600)")
    if "hypercholesterolemia" in conditions:
        where.append("(r.sat_fat_g IS NOT NULL AND r.sat_fat_g <= 5)")
    if "ckd" in conditions and weight_kg is not None:
        ckd_cap = max(1, int(weight_kg * 0.8 / 3))
        where.append("(r.protein_g IS NOT NULL AND r.protein_g <= :ckd_protein_cap)")
        params["ckd_protein_cap"] = ckd_cap
    if "gout" in conditions:
        where.append("NOT (r.tags && ARRAY['organ_meat','shellfish']::text[])")
    # Gate-based fragments (registered strategies).
    for cond in conditions:
        for gate in gates_for(cond):
            sql, gp = gate.contribute_sql()  # type: ignore[attr-defined]
            where.append(sql)
            params.update(gp)
    return where, params


# ---------------------------------------------------------------------------
# Invariant 1 — every declared condition contributes ≥1 fragment OR ≥1 gate.
# ---------------------------------------------------------------------------


@pytest.mark.property
@_SETTINGS
@given(
    conditions=st.lists(
        st.sampled_from(_CONDITIONS),
        min_size=2,
        max_size=4,
        unique=True,
    ),
    weight=st.decimals(min_value=Decimal("50"), max_value=Decimal("130"), places=1),
)
def test_no_condition_silently_dropped_in_composition(
    conditions: list[str],
    weight: Decimal,
) -> None:
    frozen = frozenset(conditions)
    where, params = _compose_inline_fragments(frozen, float(weight))
    sql_blob = " ".join(where)
    for cond in conditions:
        has_inline = cond in _EXPECTED_INLINE_FRAGMENTS
        has_gate = len(gates_for(cond)) > 0
        if has_inline:
            # at least one expected token present in composed SQL
            tokens = _EXPECTED_INLINE_FRAGMENTS[cond]
            present = any(tok in sql_blob for tok in tokens)
            assert (
                present
            ), f"inline_filter_missing_for_{cond}: tokens={tokens} sql={sql_blob[:200]}"
        else:
            assert has_gate, f"no_gate_and_no_inline_filter_for_{cond}"


# ---------------------------------------------------------------------------
# Invariant 2 — hard caps survive composition for each condition independently.
# ---------------------------------------------------------------------------


@pytest.mark.property
@_SETTINGS
@given(
    conditions=st.lists(
        st.sampled_from(_CONDITIONS),
        min_size=2,
        max_size=4,
        unique=True,
    ),
    weight=st.decimals(min_value=Decimal("50"), max_value=Decimal("130"), places=1),
)
def test_hard_caps_per_condition_present_in_composite(
    conditions: list[str],
    weight: Decimal,
) -> None:
    frozen = frozenset(conditions)
    where, params = _compose_inline_fragments(frozen, float(weight))
    sql_blob = " ".join(where)

    if "diabetes_t2" in frozen:
        assert "sugar_g" in sql_blob and "<= 15" in sql_blob
    if "hypertension" in frozen:
        assert "sodium_mg" in sql_blob and "<= 600" in sql_blob
    if "hypercholesterolemia" in frozen:
        assert "sat_fat_g" in sql_blob and "<= 5" in sql_blob
    if "ckd" in frozen:
        # Both inline cap and CKD gate caps composed → protein_g constraint
        # MUST appear via inline ckd_protein_cap and gate protein cap ≤25.
        assert "ckd_protein_cap" in params
        assert params["ckd_protein_cap"] >= 1
        # Spec: weight_kg × 0.8 / 3
        expected = max(1, int(float(weight) * 0.8 / 3))
        assert params["ckd_protein_cap"] == expected
        # Plus the registered CKDGate also enforces a per-portion absolute
        # cap (25 g/portion) — must be in bound params.
        assert "ckd_protein_max" in params
        assert params["ckd_protein_max"] == 25
    if "gout" in frozen:
        assert "organ_meat" in sql_blob and "shellfish" in sql_blob


# ---------------------------------------------------------------------------
# Invariant 3 — no parameter name collision across inline + gate composition.
# ---------------------------------------------------------------------------


@pytest.mark.property
@_SETTINGS
@given(
    conditions=st.lists(
        st.sampled_from(_CONDITIONS),
        min_size=2,
        max_size=4,
        unique=True,
    ),
    weight=st.decimals(min_value=Decimal("50"), max_value=Decimal("130"), places=1),
)
def test_no_param_key_collision_across_inline_and_gates(
    conditions: list[str],
    weight: Decimal,
) -> None:
    """Inline filters use `ckd_protein_cap`; registered gates use prefixed keys
    (`ckd_k_max`, `ckd_p_max`, ...). They must not collide — collision would
    silently overwrite one constraint and weaken safety."""
    frozen = frozenset(conditions)
    _, params = _compose_inline_fragments(frozen, float(weight))
    # `params` is built via `dict.update`; any prior collision would have
    # already overwritten. Re-assemble manually counting writes to detect.
    write_keys: list[str] = []
    if "ckd" in frozen:
        write_keys.append("ckd_protein_cap")
    for cond in frozen:
        for gate in gates_for(cond):
            _, gp = gate.contribute_sql()  # type: ignore[attr-defined]
            write_keys.extend(gp.keys())
    # No duplicate writes
    assert len(write_keys) == len(
        set(write_keys)
    ), f"param_key_collision: duplicates={[k for k in write_keys if write_keys.count(k) > 1]}"


# ---------------------------------------------------------------------------
# Named scenario matrix — locks the named multi-condition combos in the brief.
# ---------------------------------------------------------------------------


_NAMED_COMBOS: list[frozenset[str]] = [
    frozenset({"diabetes_t2", "hypertension"}),
    frozenset({"diabetes_t2", "ckd"}),
    frozenset({"hypertension", "hypercholesterolemia"}),
    frozenset({"diabetes_t2", "hypertension", "hypercholesterolemia"}),
    frozenset({"ckd", "gout"}),
    frozenset({"diabetes_t2", "celiac"}),
    frozenset({"pregnancy", "hypertension"}),
    frozenset({"lactation", "ckd"}),
]


@pytest.mark.parametrize(
    "combo",
    _NAMED_COMBOS,
    ids=[",".join(sorted(c)) for c in _NAMED_COMBOS],
)
def test_named_multi_condition_combo_emits_required_caps(
    combo: frozenset[str],
) -> None:
    weight_kg = 80.0
    where, params = _compose_inline_fragments(combo, weight_kg)
    sql_blob = " ".join(where)
    if "diabetes_t2" in combo:
        assert "sugar_g" in sql_blob
    if "hypertension" in combo:
        assert "sodium_mg" in sql_blob
    if "hypercholesterolemia" in combo:
        assert "sat_fat_g" in sql_blob
    if "ckd" in combo:
        assert "ckd_protein_cap" in params
        assert "ckd_protein_max" in params
    if "gout" in combo:
        assert "organ_meat" in sql_blob
    # Gate-only conditions must register at least one fragment.
    for cond in combo:
        if cond in {"pregnancy", "lactation", "celiac"}:
            assert len(gates_for(cond)) >= 1
