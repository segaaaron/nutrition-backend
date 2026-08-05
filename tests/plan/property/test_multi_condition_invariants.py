"""R10 — multi-condition composite invariants (in-scope conditions only).

When a user declares more than one in-scope condition simultaneously, Layer 1
eligibility composes a SQL WHERE clause purely from registered
`ConditionGate` strategies in `app/plan/domain/condition_gates/`. Since the
2026-07-09 scope reduction there are exactly three in-scope conditions:

  fatty_liver → added_sugar_g ≤ 8 AND sat_fat_g ≤ 5 AND fiber_g ≥ 3
  pregnancy   → pregnancy_safe = TRUE
  lactation   → pregnancy_safe = TRUE

(Removed 2026-07-10: the inline diabetes_t2 / hypertension / hypercholesterolemia
/ ckd / gout filters and their gates — NOVA is a general nutrition app, not a
medical tool. celiac is handled via the `gluten` allergen, lactose_intolerance
via the `dairy` allergen — never as conditions.)

This module asserts the COMPOSITE produced for any combo of the in-scope
conditions still emits every applicable gate fragment — no condition is
silently dropped when several are declared together, and the fatty_liver
hard caps survive composition.

We exercise the COMPOSITION CONTRACT (SQL strings + bound parameters), not
the live DB execution path — that is integration-tested elsewhere.
"""

from __future__ import annotations

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from app.plan.domain.condition_gates import gates_for

# The three in-scope conditions (owner decision 2026-07-09).
_CONDITIONS = (
    "fatty_liver",
    "pregnancy",
    "lactation",
)

# Per-condition tokens that MUST appear in the composed gate SQL / params.
_EXPECTED_GATE_TOKENS: dict[str, list[str]] = {
    "fatty_liver": ["fl_added_sugar_max", "fl_satfat_max", "fl_fiber_min"],
    "pregnancy": ["pregnancy_safe"],
    "lactation": ["pregnancy_safe"],
}

_SETTINGS = settings(
    max_examples=120,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.filter_too_much],
)


def _compose_gate_fragments(
    conditions: frozenset[str],
) -> tuple[list[str], dict[str, object]]:
    """Reproduce the gate fragment assembly from Layer 1 (frozen contract).

    Keeping this mirror in the test avoids importing the repository (which
    pulls in SQLAlchemy session). The dispatch must stay in sync with
    `app/plan/application/layer1_eligibility.py` — any change there should
    update this mirror, which is exactly the contract this test guards.
    """
    where: list[str] = []
    params: dict[str, object] = {}
    for cond in conditions:
        for gate in gates_for(cond):
            sql, gp = gate.contribute_sql()  # type: ignore[attr-defined]
            where.append(sql)
            params.update(gp)
    return where, params


# ---------------------------------------------------------------------------
# Invariant 1 — every declared condition contributes ≥1 gate fragment.
# ---------------------------------------------------------------------------


@pytest.mark.property
@_SETTINGS
@given(
    conditions=st.lists(
        st.sampled_from(_CONDITIONS),
        min_size=2,
        max_size=3,
        unique=True,
    ),
)
def test_no_condition_silently_dropped_in_composition(
    conditions: list[str],
) -> None:
    frozen = frozenset(conditions)
    where, params = _compose_gate_fragments(frozen)
    sql_blob = " ".join(where)
    param_blob = " ".join(params.keys())
    haystack = sql_blob + " " + param_blob
    for cond in conditions:
        assert len(gates_for(cond)) > 0, f"no_gate_for_{cond}"
        tokens = _EXPECTED_GATE_TOKENS[cond]
        present = any(tok in haystack for tok in tokens)
        assert present, f"gate_fragment_missing_for_{cond}: tokens={tokens} sql={haystack[:200]}"


# ---------------------------------------------------------------------------
# Invariant 2 — fatty_liver hard caps survive composition.
# ---------------------------------------------------------------------------


@pytest.mark.property
@_SETTINGS
@given(
    conditions=st.lists(
        st.sampled_from(_CONDITIONS),
        min_size=2,
        max_size=3,
        unique=True,
    ),
)
def test_hard_caps_per_condition_present_in_composite(
    conditions: list[str],
) -> None:
    frozen = frozenset(conditions)
    where, params = _compose_gate_fragments(frozen)
    sql_blob = " ".join(where)

    if "fatty_liver" in frozen:
        # R6 fail-closed on sugar_g and sat_fat_g; fiber is bias-admit (NULL OR >=).
        assert "r.added_sugar_g IS NOT NULL AND r.added_sugar_g <= :fl_added_sugar_max" in sql_blob
        assert "r.sat_fat_g IS NOT NULL AND r.sat_fat_g <= :fl_satfat_max" in sql_blob
        assert "r.fiber_g IS NULL OR r.fiber_g >= :fl_fiber_min" in sql_blob
        assert "COALESCE(r.fiber_g, 0)" not in sql_blob
        assert params["fl_added_sugar_max"] == 8
        assert params["fl_satfat_max"] == 5
        assert params["fl_fiber_min"] == 3
    if "pregnancy" in frozen or "lactation" in frozen:
        assert "r.pregnancy_safe = TRUE" in sql_blob


# ---------------------------------------------------------------------------
# Invariant 3 — no parameter name collision across gate composition.
# ---------------------------------------------------------------------------


@pytest.mark.property
@_SETTINGS
@given(
    conditions=st.lists(
        st.sampled_from(_CONDITIONS),
        min_size=2,
        max_size=3,
        unique=True,
    ),
)
def test_no_param_key_collision_across_gates(
    conditions: list[str],
) -> None:
    """Registered gates use prefixed keys (fatty_liver → `fl_*`;
    pregnancy/lactation carry no params). They must not collide — collision
    would silently overwrite one constraint and weaken safety."""
    frozen = frozenset(conditions)
    write_keys: list[str] = []
    for cond in frozen:
        for gate in gates_for(cond):
            _, gp = gate.contribute_sql()  # type: ignore[attr-defined]
            write_keys.extend(gp.keys())
    assert len(write_keys) == len(
        set(write_keys)
    ), f"param_key_collision: duplicates={[k for k in write_keys if write_keys.count(k) > 1]}"


# ---------------------------------------------------------------------------
# Named scenario matrix — locks the in-scope multi-condition combos.
# ---------------------------------------------------------------------------


_NAMED_COMBOS: list[frozenset[str]] = [
    frozenset({"fatty_liver", "pregnancy"}),
    frozenset({"fatty_liver", "lactation"}),
    frozenset({"pregnancy", "lactation"}),
    frozenset({"fatty_liver", "pregnancy", "lactation"}),
]


@pytest.mark.parametrize(
    "combo",
    _NAMED_COMBOS,
    ids=[",".join(sorted(c)) for c in _NAMED_COMBOS],
)
def test_named_multi_condition_combo_emits_required_gates(
    combo: frozenset[str],
) -> None:
    where, params = _compose_gate_fragments(combo)
    sql_blob = " ".join(where)
    if "fatty_liver" in combo:
        assert "fl_added_sugar_max" in params
        assert "fl_satfat_max" in params
        assert "fl_fiber_min" in params
    if "pregnancy" in combo or "lactation" in combo:
        assert "r.pregnancy_safe = TRUE" in sql_blob
    # Every in-scope condition must register at least one gate fragment.
    for cond in combo:
        assert len(gates_for(cond)) >= 1
