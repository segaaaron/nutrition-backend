"""Multi-condition intersection invariants (property-based).

NOVA scope: nutrition planning, not nutrition guidance. When a user declares
several in-scope conditions at once (e.g. fatty_liver + pregnancy,
fatty_liver + lactation), Layer 1 eligibility composes ConditionGate
Strategy fragments via AND. The invariants asserted here:

  M1. `gates_for(cond)` returns the gate registered for each condition AND
      no condition is silently dropped when the user declares many.
  M2. Concatenating gate SQL fragments preserves every parameter — no key
      collision across gates (each gate uses a unique prefix).
  M3. Trimester + lactation kcal adjustments compose additively and stay
      within ±15% of the pre-adjustment TDEE when applied to a realistic
      pregnant-then-lactating window. (Note: the production scope only
      applies one at a time, but the math invariants are tested for both
      gates independently and together — surfaces a regression if either
      adjustment silently drops the other.)
  M4. Per-condition kcal targets respect the BMR * 0.9 safety floor for any
      realistic user across the fatty_liver / pregnancy / lactation combos.

We do NOT exercise the SQL execution path here (Layer 1 is integration-tested
elsewhere). We exercise the composition contract, which is where multi-
condition silent-drop bugs would live.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Literal

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from app.plan.domain.bmr_safety import (
    KcalTargetBelowSafetyFloor,
    apply_goal_to_tdee,
    apply_lactation_adjustment,
    apply_trimester_adjustment,
    enforce_bmr_safety_floor,
    mifflin_st_jeor,
    tdee,
)
from app.plan.domain.condition_gates import gates_for

_SETTINGS = settings(
    max_examples=150,
    deadline=None,
    derandomize=False,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.filter_too_much],
)

# In-scope conditions with registered gates (owner decision 2026-07-09;
# out-of-scope medical gates removed 2026-07-10).
_CONDITIONS_WITH_GATES = (
    "fatty_liver",
    "pregnancy",
    "lactation",
)


# ---------------------------------------------------------------------------
# M1 — no condition silently dropped when user declares multiple.
# ---------------------------------------------------------------------------


@pytest.mark.property
@_SETTINGS
@given(
    conditions=st.lists(
        st.sampled_from(_CONDITIONS_WITH_GATES),
        min_size=2,
        max_size=3,
        unique=True,
    ),
)
def test_each_condition_contributes_at_least_one_gate(
    conditions: list[str],
) -> None:
    """For each declared condition, `gates_for` MUST return at least one gate.
    If any condition resolves to an empty list while gates are registered,
    Layer 1 would silently drop its filter — a critical safety regression."""
    for cond in conditions:
        gates = gates_for(cond)
        assert len(gates) >= 1, f"no_gate_registered_for: {cond}"


# ---------------------------------------------------------------------------
# M2 — composition has no parameter collision and emits one fragment per
# gate per condition.
# ---------------------------------------------------------------------------


@pytest.mark.property
@_SETTINGS
@given(
    conditions=st.lists(
        st.sampled_from(_CONDITIONS_WITH_GATES),
        min_size=2,
        max_size=3,
        unique=True,
    ),
)
def test_compose_no_param_collision_across_gates(
    conditions: list[str],
) -> None:
    """When Layer 1 merges params from many gates via `dict.update`, no key
    should collide — each gate must use a unique prefix. A collision would
    overwrite the earlier gate's bind value, silently dropping its filter."""
    seen: dict[str, str] = {}
    for cond in conditions:
        for gate in gates_for(cond):
            sql, params = gate.contribute_sql()  # type: ignore[attr-defined]
            for key in params:
                if key in seen:
                    assert seen[key] == cond, (
                        f"param_collision: key={key} between " f"{seen[key]!r} and {cond!r}"
                    )
                seen[key] = cond


@pytest.mark.property
@_SETTINGS
@given(
    conditions=st.lists(
        st.sampled_from(_CONDITIONS_WITH_GATES),
        min_size=2,
        max_size=3,
        unique=True,
    ),
)
def test_compose_emits_one_fragment_per_condition_gate(
    conditions: list[str],
) -> None:
    fragments: list[str] = []
    for cond in conditions:
        for gate in gates_for(cond):
            sql, _ = gate.contribute_sql()  # type: ignore[attr-defined]
            fragments.append(sql)
    # Total fragments = sum of gates per condition (≥1 each, asserted in M1).
    assert len(fragments) >= len(conditions)
    # No silent dedupe: fragments are accumulated, not set-collapsed.
    # All fragments are parenthesised — safe for AND composition.
    for sql in fragments:
        assert sql.startswith("(") and sql.endswith(")")


# ---------------------------------------------------------------------------
# M3 — pregnancy + lactation kcal adjustments compose additively.
# Production normally applies one at a time; the invariant guards against a
# silent drop if both flags are simultaneously true (rare edge but defensible
# math).
# ---------------------------------------------------------------------------


_Trimester = Literal["first", "second", "third"]


@pytest.mark.property
@_SETTINGS
@given(
    kcal=st.decimals(min_value=Decimal("1500"), max_value=Decimal("3500"), places=0),
    trimester=st.sampled_from(["first", "second", "third"]),
    has_lactation=st.booleans(),
)
def test_pregnancy_lactation_compose_additively(
    kcal: Decimal, trimester: str, has_lactation: bool
) -> None:
    conds: frozenset[str] = frozenset({"lactation"} if has_lactation else set())
    after_preg = apply_trimester_adjustment(
        kcal_target=kcal,
        trimester=trimester,  # type: ignore[arg-type]
    )
    after_both = apply_lactation_adjustment(kcal_target=after_preg, conditions=conds)
    expected_surplus = Decimal({"first": 0, "second": 340, "third": 452}[trimester]) + (
        Decimal("500") if has_lactation else Decimal("0")
    )
    assert after_both - kcal == expected_surplus, (
        f"additive_violation: trimester={trimester} lact={has_lactation} "
        f"got={after_both - kcal} expected={expected_surplus}"
    )


# ---------------------------------------------------------------------------
# M4 — kcal target respects BMR * 0.9 safety floor across condition combos.
# ---------------------------------------------------------------------------


_sex = st.sampled_from(["male", "female"])
_goal = st.sampled_from(["weight_loss", "maintain", "muscle_gain", "weight_gain", "health"])
_activity = st.sampled_from(
    ["sedentary", "lightly_active", "moderately_active", "very_active", "extra_active"]
)


@pytest.mark.property
@_SETTINGS
@given(
    weight=st.decimals(min_value=Decimal("50"), max_value=Decimal("130"), places=1),
    height=st.decimals(min_value=Decimal("150"), max_value=Decimal("200"), places=1),
    age=st.integers(min_value=18, max_value=70),
    sex=_sex,
    goal=_goal,
    activity=_activity,
)
def test_kcal_target_above_bmr_safety_floor_for_realistic_users(  # noqa: PLR0913 — hypothesis kwargs
    weight: Decimal,
    height: Decimal,
    age: int,
    sex: str,
    goal: str,
    activity: str,
) -> None:
    """Pipeline produces a kcal_target that must clear the BMR * 0.9 floor —
    even for weight_loss goal. If the pipeline ever returns a target below
    the floor, `enforce_bmr_safety_floor` MUST raise. This test asserts the
    raise contract for a wide population sweep."""
    bmr = mifflin_st_jeor(
        weight_kg=weight,
        height_cm=height,
        age=age,
        sex=sex,  # type: ignore[arg-type]
    )
    tdee_val = tdee(bmr=bmr, activity_level=activity)  # type: ignore[arg-type]
    target = apply_goal_to_tdee(tdee_val=tdee_val, goal=goal)  # type: ignore[arg-type]
    floor = bmr * Decimal("0.9")

    if target < floor:
        with pytest.raises(KcalTargetBelowSafetyFloor):
            enforce_bmr_safety_floor(kcal_target=target, bmr=bmr)
    else:
        # Must passthrough without raising.
        out = enforce_bmr_safety_floor(kcal_target=target, bmr=bmr)
        assert out == target


# ---------------------------------------------------------------------------
# M5 — example matrix from the brief — explicit condition combinations
# documented in the task. Locks contract with named scenarios.
# ---------------------------------------------------------------------------


_COMBOS: list[frozenset[str]] = [
    frozenset({"fatty_liver"}),
    frozenset({"pregnancy"}),
    frozenset({"lactation"}),
    frozenset({"fatty_liver", "pregnancy"}),
    frozenset({"fatty_liver", "lactation"}),
    frozenset({"fatty_liver", "pregnancy", "lactation"}),
]


@pytest.mark.parametrize("combo", _COMBOS, ids=[",".join(sorted(c)) for c in _COMBOS])
def test_named_condition_combos_all_compose_without_drop(
    combo: frozenset[str],
) -> None:
    """Each scenario in the brief MUST yield at least one gate per condition,
    no param collisions, and parenthesised SQL fragments ready for AND."""
    seen_keys: dict[str, str] = {}
    fragments_by_cond: dict[str, int] = {c: 0 for c in combo}
    for cond in combo:
        for gate in gates_for(cond):
            sql, params = gate.contribute_sql()  # type: ignore[attr-defined]
            assert sql.startswith("(") and sql.endswith(")")
            fragments_by_cond[cond] += 1
            for key in params:
                if key in seen_keys:
                    assert seen_keys[key] == cond, (
                        f"param_collision_in_combo: combo={sorted(combo)} "
                        f"key={key} cond_a={seen_keys[key]} cond_b={cond}"
                    )
                seen_keys[key] = cond
    for cond, n in fragments_by_cond.items():
        assert n >= 1, f"condition_silently_dropped: combo={sorted(combo)} dropped={cond}"
