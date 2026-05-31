"""Mifflin-St Jeor property + spot tests."""
from __future__ import annotations

from decimal import Decimal

import pytest
from hypothesis import given, strategies as st

from app.nutrition.domain.mifflin_st_jeor import compute_bmr


@pytest.mark.parametrize(
    "sex,w,h,a,expected",
    [
        # Published Mifflin example: man 80 kg, 180 cm, 30y -> 10*80 + 6.25*180 - 5*30 + 5 = 800+1125-150+5 = 1780
        ("male",   80, 180, 30, 1780),
        # Woman 65, 165, 28 -> 650 + 1031.25 - 140 - 161 = 1380.25 → 1380
        ("female", 65, 165, 28, 1380),
        # Woman 70, 170, 40 -> 700 + 1062.5 - 200 - 161 = 1401.5 → 1402
        ("female", 70, 170, 40, 1402),
    ],
)
def test_published_examples(sex, w, h, a, expected):
    assert compute_bmr(sex=sex, weight_kg=w, height_cm=h, age=a) == expected


def test_male_minus_female_is_166():
    """Mifflin sex offset: (+5) - (-161) = 166 for identical inputs."""
    same = dict(weight_kg=Decimal("70"), height_cm=Decimal("170"), age=30)
    diff = compute_bmr(sex="male", **same) - compute_bmr(sex="female", **same)
    assert diff == 166


@given(
    sex=st.sampled_from(["male", "female"]),
    w=st.integers(min_value=40, max_value=200),
    h=st.integers(min_value=140, max_value=210),
    a=st.integers(min_value=18, max_value=80),
)
def test_bmr_bounded(sex, w, h, a):
    bmr = compute_bmr(sex=sex, weight_kg=w, height_cm=h, age=a)
    assert 800 <= bmr <= 4000, f"BMR {bmr} out of clinical range"
