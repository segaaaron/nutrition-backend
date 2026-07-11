"""Direct unit + property tests for app.plan.domain.bmr_safety.

Goal: kill behavioural mutants enumerated in
``docs/qa/mutation_baseline_sprint3.md`` (Sprint 3 baseline 5.8% -> target ≥70%).

Each test maps to a class of mutation:
- exact-value pins (kills arithmetic-operator + constant mutations)
- monotonicity properties (kills `<`/`>` swaps, `*`/`/` swaps)
- exception type + message pins (kills exception-message mutations)
- exhaustive Goal / ActivityLevel / trimester enumeration (kills branch
  flips like ``elif goal == "muscle_gain"`` -> ``elif goal != "muscle_gain"``)
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from app.plan.domain.bmr_safety import (
    KcalTargetBelowSafetyFloor,
    apply_goal_to_tdee,
    apply_lactation_adjustment,
    apply_trimester_adjustment,
    cunningham,
    enforce_bmr_safety_floor,
    select_bmr,
    tdee,
)

# ---------------------------------------------------------------------------
# cunningham
# ---------------------------------------------------------------------------


class TestCunningham:
    @pytest.mark.parametrize(
        "lbm,expected",
        [
            (Decimal("0"), Decimal("500")),
            (Decimal("50"), Decimal("1600")),  # 500 + 22*50
            (Decimal("60"), Decimal("1820")),
            (Decimal("70"), Decimal("2040")),
            (Decimal("80.5"), Decimal("2271")),  # 500 + 22*80.5 = 2271
        ],
    )
    def test_cunningham_returns_exact_value_for_known_lbm(
        self, lbm: Decimal, expected: Decimal
    ) -> None:
        assert cunningham(lbm_kg=lbm) == expected

    def test_cunningham_uses_constant_500_offset(self) -> None:
        # Kills mutation of the 500 literal.
        assert cunningham(lbm_kg=Decimal("0")) == Decimal("500")

    def test_cunningham_uses_constant_22_slope(self) -> None:
        # delta = 22 kcal per kg LBM. Kills mutation of the 22 literal.
        assert cunningham(lbm_kg=Decimal("11")) - cunningham(lbm_kg=Decimal("10")) == Decimal("22")

    @given(
        lbm_a=st.decimals(
            min_value=Decimal("30"),
            max_value=Decimal("100"),
            places=2,
            allow_nan=False,
            allow_infinity=False,
        ),
        delta=st.decimals(
            min_value=Decimal("1"),
            max_value=Decimal("50"),
            places=2,
            allow_nan=False,
            allow_infinity=False,
        ),
    )
    @settings(max_examples=50, suppress_health_check=[HealthCheck.too_slow])
    def test_cunningham_monotonic_increasing_in_lbm(self, lbm_a: Decimal, delta: Decimal) -> None:
        assert cunningham(lbm_kg=lbm_a + delta) > cunningham(lbm_kg=lbm_a)


# ---------------------------------------------------------------------------
# select_bmr
# ---------------------------------------------------------------------------


class TestSelectBmr:
    def test_select_bmr_returns_mifflin_when_not_athletic(self) -> None:
        bmr, method = select_bmr(
            weight_kg=Decimal("70"),
            height_cm=Decimal("170"),
            age=30,
            sex="male",
            bodyfat_pct=Decimal("15"),
            athletic=False,
        )
        assert method == "mifflin"
        # 10*70 + 6.25*170 - 5*30 + 5 = 700 + 1062.5 - 150 + 5 = 1617.5 -> 1618
        assert bmr == Decimal("1618")

    def test_select_bmr_athletic_defaults_to_false(self) -> None:
        # Pin the default value of `athletic` kwarg. Mutant flipping the
        # default to True would silently switch to cunningham when bodyfat
        # is provided for a non-athlete (e.g. a sedentary user with a DEXA
        # scan), under-estimating BMR. Kills mutant 28.
        _, method_default = select_bmr(
            weight_kg=Decimal("70"),
            height_cm=Decimal("170"),
            age=30,
            sex="male",
            bodyfat_pct=Decimal("25"),
            # athletic intentionally omitted — relies on the default.
        )
        assert method_default == "mifflin"

    def test_select_bmr_returns_mifflin_when_athletic_but_bodyfat_unknown(
        self,
    ) -> None:
        _, method = select_bmr(
            weight_kg=Decimal("70"),
            height_cm=Decimal("170"),
            age=30,
            sex="male",
            bodyfat_pct=None,
            athletic=True,
        )
        assert method == "mifflin"

    def test_select_bmr_returns_cunningham_when_athletic_and_bodyfat_known(
        self,
    ) -> None:
        bmr, method = select_bmr(
            weight_kg=Decimal("80"),
            height_cm=Decimal("180"),
            age=28,
            sex="male",
            bodyfat_pct=Decimal("10"),
            athletic=True,
        )
        assert method == "cunningham"
        # lbm = 80 * (1 - 10/100) = 72
        # cunningham = 500 + 22*72 = 2084
        assert bmr == Decimal("2084")

    def test_select_bmr_female_cunningham_uses_lbm_from_bodyfat(self) -> None:
        bmr, method = select_bmr(
            weight_kg=Decimal("60"),
            height_cm=Decimal("165"),
            age=25,
            sex="female",
            bodyfat_pct=Decimal("20"),
            athletic=True,
        )
        assert method == "cunningham"
        # lbm = 60 * 0.80 = 48
        # cunningham = 500 + 22*48 = 1556
        assert bmr == Decimal("1556")


# ---------------------------------------------------------------------------
# tdee
# ---------------------------------------------------------------------------


# These multiplier pins kill:
#   - operator swap `bmr * mult` -> `bmr / mult`
#   - per-PAL constant mutations (1.2 -> 1.3, etc.)
#   - dict-key swaps
TDEE_PAL_CASES: list[tuple[str, Decimal, Decimal]] = [
    # (activity_level, bmr, expected_tdee)
    ("sedentary", Decimal("1500"), Decimal("1800")),  # 1500 * 1.2
    (
        "lightly_active",
        Decimal("1500"),
        Decimal("2062"),
    ),  # 1500 * 1.375 = 2062.5 -> 2062 (half-even)
    ("moderately_active", Decimal("1500"), Decimal("2325")),  # 1500 * 1.55
    (
        "very_active",
        Decimal("1500"),
        Decimal("2588"),
    ),  # 1500 * 1.725 = 2587.5 -> 2588 (half-even rounds to even)
    ("extra_active", Decimal("1500"), Decimal("2850")),  # 1500 * 1.9
]


class TestTdee:
    @pytest.mark.parametrize("activity_level,bmr,expected", TDEE_PAL_CASES)
    def test_tdee_returns_exact_value_per_pal_level(
        self, activity_level: str, bmr: Decimal, expected: Decimal
    ) -> None:
        # type: ignore[arg-type] — Literal narrowing not needed at runtime.
        assert tdee(bmr=bmr, activity_level=activity_level) == expected  # type: ignore[arg-type]

    def test_tdee_monotonic_across_all_pal_levels(self) -> None:
        # Kills `*` -> `/`, multiplier permutations, and ordering bugs.
        bmr = Decimal("1700")
        ordered = [
            tdee(bmr=bmr, activity_level="sedentary"),
            tdee(bmr=bmr, activity_level="lightly_active"),
            tdee(bmr=bmr, activity_level="moderately_active"),
            tdee(bmr=bmr, activity_level="very_active"),
            tdee(bmr=bmr, activity_level="extra_active"),
        ]
        assert ordered == sorted(ordered)
        assert ordered[0] < ordered[-1]

    @given(
        bmr=st.decimals(
            min_value=Decimal("1000"),
            max_value=Decimal("3000"),
            places=0,
            allow_nan=False,
            allow_infinity=False,
        )
    )
    @settings(max_examples=40, suppress_health_check=[HealthCheck.too_slow])
    def test_tdee_sedentary_strictly_less_than_extra_active(self, bmr: Decimal) -> None:
        assert tdee(bmr=bmr, activity_level="sedentary") < tdee(
            bmr=bmr, activity_level="extra_active"
        )

    @given(
        bmr=st.decimals(
            min_value=Decimal("1000"),
            max_value=Decimal("3000"),
            places=0,
            allow_nan=False,
            allow_infinity=False,
        )
    )
    @settings(max_examples=40, suppress_health_check=[HealthCheck.too_slow])
    def test_tdee_is_strictly_greater_than_bmr_for_any_pal(self, bmr: Decimal) -> None:
        # All PAL multipliers > 1, so tdee > bmr always.
        for level in (
            "sedentary",
            "lightly_active",
            "moderately_active",
            "very_active",
            "extra_active",
        ):
            assert tdee(bmr=bmr, activity_level=level) > bmr  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# apply_goal_to_tdee
# ---------------------------------------------------------------------------


class TestApplyGoalToTdee:
    def test_weight_loss_caps_at_500_when_tdee_is_high(self) -> None:
        # 25% of 3000 = 750 > 500, so cut = 500.
        assert apply_goal_to_tdee(tdee_val=Decimal("3000"), goal="weight_loss") == Decimal("2500")

    def test_weight_loss_uses_25pct_when_tdee_is_low(self) -> None:
        # 25% of 1600 = 400 < 500, so cut = 400.
        assert apply_goal_to_tdee(tdee_val=Decimal("1600"), goal="weight_loss") == Decimal("1200")

    def test_weight_loss_boundary_exactly_2000_tdee(self) -> None:
        # 25% of 2000 = 500 == 500, the `<` comparator picks pct (== branch).
        # Cut applied is 500 (either path), result identical.
        assert apply_goal_to_tdee(tdee_val=Decimal("2000"), goal="weight_loss") == Decimal("1500")

    def test_muscle_gain_adds_exactly_250(self) -> None:
        # Kills `elif goal == "muscle_gain"` -> `elif goal != ...` mutation
        # (the surplus value would land on a different goal otherwise).
        assert apply_goal_to_tdee(tdee_val=Decimal("2200"), goal="muscle_gain") == Decimal("2450")

    def test_muscle_gain_constant_is_250_not_300(self) -> None:
        # Pins the literal 250 vs the 300 used by weight_gain.
        delta = apply_goal_to_tdee(tdee_val=Decimal("2000"), goal="muscle_gain") - Decimal("2000")
        assert delta == Decimal("250")

    def test_weight_gain_adds_exactly_300(self) -> None:
        assert apply_goal_to_tdee(tdee_val=Decimal("2200"), goal="weight_gain") == Decimal("2500")

    def test_weight_gain_constant_is_300_not_250(self) -> None:
        delta = apply_goal_to_tdee(tdee_val=Decimal("2000"), goal="weight_gain") - Decimal("2000")
        assert delta == Decimal("300")

    @pytest.mark.parametrize("goal", ["maintain", "health"])
    def test_maintain_and_health_return_tdee_unchanged(self, goal: str) -> None:
        assert apply_goal_to_tdee(
            tdee_val=Decimal("2200"), goal=goal  # type: ignore[arg-type]
        ) == Decimal("2200")

    def test_weight_loss_strictly_below_tdee(self) -> None:
        # Property: weight_loss < maintain.
        tdee_val = Decimal("2400")
        assert apply_goal_to_tdee(tdee_val=tdee_val, goal="weight_loss") < tdee_val

    def test_muscle_gain_strictly_above_tdee(self) -> None:
        tdee_val = Decimal("2400")
        assert apply_goal_to_tdee(tdee_val=tdee_val, goal="muscle_gain") > tdee_val

    def test_weight_gain_strictly_above_tdee(self) -> None:
        tdee_val = Decimal("2400")
        assert apply_goal_to_tdee(tdee_val=tdee_val, goal="weight_gain") > tdee_val

    def test_weight_gain_surplus_exceeds_muscle_gain_surplus(self) -> None:
        # 300 > 250: pins both literals against swap.
        tdee_val = Decimal("2200")
        assert apply_goal_to_tdee(tdee_val=tdee_val, goal="weight_gain") > apply_goal_to_tdee(
            tdee_val=tdee_val, goal="muscle_gain"
        )

    @given(
        tdee_val=st.decimals(
            min_value=Decimal("1200"),
            max_value=Decimal("4000"),
            places=0,
            allow_nan=False,
            allow_infinity=False,
        )
    )
    @settings(max_examples=50, suppress_health_check=[HealthCheck.too_slow])
    def test_property_goal_ordering(self, tdee_val: Decimal) -> None:
        wl = apply_goal_to_tdee(tdee_val=tdee_val, goal="weight_loss")
        mt = apply_goal_to_tdee(tdee_val=tdee_val, goal="maintain")
        mg = apply_goal_to_tdee(tdee_val=tdee_val, goal="muscle_gain")
        wg = apply_goal_to_tdee(tdee_val=tdee_val, goal="weight_gain")
        assert wl < mt < mg < wg

    @given(
        tdee_val=st.decimals(
            min_value=Decimal("1200"),
            max_value=Decimal("4000"),
            places=0,
            allow_nan=False,
            allow_infinity=False,
        )
    )
    @settings(max_examples=50, suppress_health_check=[HealthCheck.too_slow])
    def test_property_weight_loss_deficit_capped_at_25pct(self, tdee_val: Decimal) -> None:
        """Regression guard (2026-07-09): the old flat −500 delta could cut
        >25% of TDEE on small frames, over-deficiting them below the BMR
        safety floor. The capped adjustment must NEVER cut more than
        min(500, 25% TDEE). Since a sedentary weight_loss target equals
        0.75*TDEE = 0.9*BMR (the floor), this cap is what keeps small users
        at/above the floor.
        """
        result = apply_goal_to_tdee(tdee_val=tdee_val, goal="weight_loss")
        deficit = tdee_val - result
        cap = min(Decimal("500"), tdee_val * Decimal("0.25"))
        # result is quantized to the nearest integer → allow ±1 kcal slack.
        assert Decimal("0") <= deficit <= cap + 1


# ---------------------------------------------------------------------------
# enforce_bmr_safety_floor
# ---------------------------------------------------------------------------


class TestEnforceBmrSafetyFloor:
    def test_target_above_floor_passthrough(self) -> None:
        # floor = 1500 * 0.9 = 1350. Target 1400 > 1350 passes.
        assert enforce_bmr_safety_floor(
            kcal_target=Decimal("1400"), bmr=Decimal("1500")
        ) == Decimal("1400")

    def test_target_exactly_at_floor_passes(self) -> None:
        # floor = 1500 * 0.9 = 1350. Strict `<` => `==` passes.
        # Kills `<` -> `<=` mutation.
        assert enforce_bmr_safety_floor(
            kcal_target=Decimal("1350"), bmr=Decimal("1500")
        ) == Decimal("1350")

    def test_target_below_floor_raises(self) -> None:
        with pytest.raises(KcalTargetBelowSafetyFloor):
            enforce_bmr_safety_floor(kcal_target=Decimal("1349"), bmr=Decimal("1500"))

    def test_exception_message_contains_canonical_token(self) -> None:
        # Operators key alerts off this string. Kills exception-message mutants.
        with pytest.raises(KcalTargetBelowSafetyFloor) as exc:
            enforce_bmr_safety_floor(kcal_target=Decimal("1000"), bmr=Decimal("1500"))
        msg = str(exc.value)
        # Pin the message exactly — operators key alerts off this string.
        # Kills mutation-marker wrapping (e.g. "XX...XX") of the f-string.
        assert msg.startswith("kcal_target_below_bmr_safety_floor:")
        assert "target=1000" in msg
        assert "floor=" in msg
        # No mutation marker / wrapper allowed.
        assert "XX" not in msg

    def test_exception_carries_target_and_floor_attributes(self) -> None:
        with pytest.raises(KcalTargetBelowSafetyFloor) as exc:
            enforce_bmr_safety_floor(kcal_target=Decimal("1000"), bmr=Decimal("1500"))
        assert exc.value.target == Decimal("1000")
        # floor = 1500 * 0.9 = 1350.0
        assert exc.value.floor == Decimal("1500") * Decimal("0.9")

    def test_floor_uses_constant_0_9_not_0_8(self) -> None:
        # Pins the 0.9 constant. With 0.8, floor = 1200 and 1250 would pass.
        # With 0.9, floor = 1350 and 1250 must raise.
        with pytest.raises(KcalTargetBelowSafetyFloor):
            enforce_bmr_safety_floor(kcal_target=Decimal("1250"), bmr=Decimal("1500"))

    @given(
        bmr=st.decimals(
            min_value=Decimal("1200"),
            max_value=Decimal("2200"),
            places=0,
            allow_nan=False,
            allow_infinity=False,
        )
    )
    @settings(max_examples=40, suppress_health_check=[HealthCheck.too_slow])
    def test_property_floor_is_exactly_90pct_of_bmr(self, bmr: Decimal) -> None:
        # Any target below 0.9*bmr by a single unit MUST raise.
        floor = bmr * Decimal("0.9")
        with pytest.raises(KcalTargetBelowSafetyFloor):
            enforce_bmr_safety_floor(kcal_target=floor - Decimal("1"), bmr=bmr)
        # And any target at or above the floor MUST pass.
        assert enforce_bmr_safety_floor(kcal_target=floor, bmr=bmr) == floor


# ---------------------------------------------------------------------------
# apply_lactation_adjustment
# ---------------------------------------------------------------------------


class TestApplyLactationAdjustment:
    def test_no_adjustment_when_lactation_absent(self) -> None:
        assert apply_lactation_adjustment(
            kcal_target=Decimal("1800"), conditions=frozenset()
        ) == Decimal("1800")

    def test_no_adjustment_when_unrelated_condition_present(self) -> None:
        assert apply_lactation_adjustment(
            kcal_target=Decimal("1800"),
            conditions=frozenset({"fatty_liver"}),
        ) == Decimal("1800")

    def test_adds_exactly_500_when_lactation_present(self) -> None:
        # Kills constant mutation (e.g. 500 -> 501) and the `in` branch flip.
        assert apply_lactation_adjustment(
            kcal_target=Decimal("1800"),
            conditions=frozenset({"lactation"}),
        ) == Decimal("2300")

    def test_lactation_surplus_is_500_not_340(self) -> None:
        # Pin against the pregnancy T2 value (340), which is the closest
        # numeric neighbour and the obvious mutation target.
        delta = apply_lactation_adjustment(
            kcal_target=Decimal("2000"),
            conditions=frozenset({"lactation"}),
        ) - Decimal("2000")
        assert delta == Decimal("500")

    def test_handles_lactation_combined_with_other_conditions(self) -> None:
        assert apply_lactation_adjustment(
            kcal_target=Decimal("1800"),
            conditions=frozenset({"lactation", "fatty_liver"}),
        ) == Decimal("2300")


# ---------------------------------------------------------------------------
# apply_trimester_adjustment
# ---------------------------------------------------------------------------


class TestApplyTrimesterAdjustment:
    def test_none_trimester_returns_target_unchanged(self) -> None:
        assert apply_trimester_adjustment(kcal_target=Decimal("1800"), trimester=None) == Decimal(
            "1800"
        )

    def test_first_trimester_adds_zero(self) -> None:
        # IOM DRI 2002: T1 = +0 kcal. Pins the 0 constant.
        assert apply_trimester_adjustment(
            kcal_target=Decimal("1800"), trimester="first"
        ) == Decimal("1800")

    def test_second_trimester_adds_exactly_340(self) -> None:
        assert apply_trimester_adjustment(
            kcal_target=Decimal("1800"), trimester="second"
        ) == Decimal("2140")

    def test_third_trimester_adds_exactly_452(self) -> None:
        assert apply_trimester_adjustment(
            kcal_target=Decimal("1800"), trimester="third"
        ) == Decimal("2252")

    def test_trimester_surplus_strictly_increases_t1_to_t2_to_t3(self) -> None:
        # Property: 0 < 340 < 452. Pins all three constants and ordering.
        t = Decimal("1800")
        a = apply_trimester_adjustment(kcal_target=t, trimester="first")
        b = apply_trimester_adjustment(kcal_target=t, trimester="second")
        c = apply_trimester_adjustment(kcal_target=t, trimester="third")
        assert a < b < c

    def test_second_trimester_surplus_is_340_not_300_or_500(self) -> None:
        # Pin against neighbour constants from other functions (300=weight_gain,
        # 500=lactation/weight_loss-cap) which are obvious mutation targets.
        delta = apply_trimester_adjustment(
            kcal_target=Decimal("2000"), trimester="second"
        ) - Decimal("2000")
        assert delta == Decimal("340")
        assert delta != Decimal("300")
        assert delta != Decimal("500")

    def test_third_trimester_surplus_is_452_not_340(self) -> None:
        delta = apply_trimester_adjustment(
            kcal_target=Decimal("2000"), trimester="third"
        ) - Decimal("2000")
        assert delta == Decimal("452")
