"""Cross-check BMR: legacy float impl vs new Decimal impl.

Master plan risk F1 (ADR-0009): two parallel implementations may diverge
silently until Track C migration. This test runs every PR — any drift > 1 kcal
on rounded outputs across a realistic population fails the build.

Population: 1000 deterministic profiles spanning sex × age × weight × height.
Bound: `|legacy_bmr - round(new_bmr)| <= 1` for every profile.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from app.nutrition.domain.mifflin_st_jeor import compute_bmr as legacy_bmr
from app.plan.domain.bmr_safety import mifflin_st_jeor as new_bmr


@settings(max_examples=1000, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(
    sex=st.sampled_from(["male", "female"]),
    weight_kg=st.decimals(
        min_value=Decimal("40"),
        max_value=Decimal("200"),
        allow_nan=False,
        allow_infinity=False,
        places=1,
    ),
    height_cm=st.decimals(
        min_value=Decimal("140"),
        max_value=Decimal("210"),
        allow_nan=False,
        allow_infinity=False,
        places=1,
    ),
    age=st.integers(min_value=18, max_value=80),
)
def test_legacy_vs_new_bmr_within_1_kcal(
    sex: str,
    weight_kg: Decimal,
    height_cm: Decimal,
    age: int,
) -> None:
    legacy = legacy_bmr(sex=sex, weight_kg=weight_kg, height_cm=height_cm, age=age)  # type: ignore[arg-type]
    new = new_bmr(weight_kg=weight_kg, height_cm=height_cm, age=age, sex=sex)  # type: ignore[arg-type]
    # New returns Decimal; quantize to int kcal for fair comparison.
    new_int = int(new)
    delta = abs(legacy - new_int)
    assert delta <= 1, (
        f"BMR cross-check drift: legacy={legacy} new={new_int} delta={delta} "
        f"sex={sex} w={weight_kg} h={height_cm} age={age}"
    )


@pytest.mark.parametrize(
    "sex, weight_kg, height_cm, age",
    [
        ("male", Decimal("70"), Decimal("175"), 30),
        ("female", Decimal("60"), Decimal("165"), 35),
        ("male", Decimal("90"), Decimal("180"), 45),
        ("female", Decimal("50"), Decimal("155"), 25),
        ("male", Decimal("120"), Decimal("190"), 22),
        ("female", Decimal("85"), Decimal("170"), 55),
    ],
)
def test_legacy_vs_new_bmr_known_anchors(
    sex: str,
    weight_kg: Decimal,
    height_cm: Decimal,
    age: int,
) -> None:
    """Anchor cases — guard against silent regression on representative profiles."""
    legacy = legacy_bmr(sex=sex, weight_kg=weight_kg, height_cm=height_cm, age=age)  # type: ignore[arg-type]
    new = new_bmr(weight_kg=weight_kg, height_cm=height_cm, age=age, sex=sex)  # type: ignore[arg-type]
    assert abs(legacy - int(new)) <= 1
