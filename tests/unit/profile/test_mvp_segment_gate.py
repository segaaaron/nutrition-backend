"""MVP segment gate — refuses clinical conditions + US region for narrow MVP.

Catalog audit 2026-06-01: catalog + algorithms not safe for diabetes_t2,
diabetes_t1, pregnancy, lactation, ckd, or US region. Gate enforced at
profile boundary (CompleteOnboarding, UpdateProfile) and toggled by
`settings.mvp_segment_gate_enabled`.
"""
from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest

from app.core.config import get_settings
from app.core.errors import BusinessRuleViolation
from app.profile.application.use_cases import _enforce_mvp_segment_gate
from app.profile.domain.entities import UserProfile


def _valid_profile(**overrides: object) -> UserProfile:
    p = UserProfile(
        user_id=uuid4(), age=30, sex="male",
        weight_kg=Decimal("70"), height_cm=Decimal("175"),
        goal="weight_loss", activity_level="moderately_active",
        country="PE", region="latam",
    )
    for k, v in overrides.items():
        setattr(p, k, v)
    return p


@pytest.fixture(autouse=True)
def _clear_settings_cache() -> None:
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_safe_profile_passes() -> None:
    _enforce_mvp_segment_gate(_valid_profile())


@pytest.mark.parametrize("condition", ["diabetes_t1"])
def test_blocked_conditions_raise(condition: str) -> None:
    """Only diabetes_t1 remains gated post H2 sweep (insulin timing scope)."""
    p = _valid_profile(medical_conditions=[condition])
    with pytest.raises(BusinessRuleViolation) as ei:
        _enforce_mvp_segment_gate(p)
    assert "segment_unsupported_mvp" in str(ei.value)
    assert condition in str(ei.value)


@pytest.mark.parametrize(
    "condition",
    ["lactation", "diabetes_t2", "ckd", "hypertension", "celiac", "pregnancy"],
)
def test_lifted_conditions_now_pass(condition: str) -> None:
    """H2 lifts shipped 2026-06-01:
    - lactation ADR-0016
    - diabetes_t2 ADR-0018
    - ckd ADR-0019
    - pregnancy ADR-0020
    - hypertension + celiac formalized (Layer 1 inline → Strategy registry).
    """
    p = _valid_profile(medical_conditions=[condition])
    _enforce_mvp_segment_gate(p)


def test_blocked_region_us_raises() -> None:
    p = _valid_profile(region="us")
    with pytest.raises(BusinessRuleViolation) as ei:
        _enforce_mvp_segment_gate(p)
    assert "segment_unsupported_mvp:region:us" in str(ei.value)


def test_allowed_region_latam_passes() -> None:
    _enforce_mvp_segment_gate(_valid_profile(region="latam"))


def test_gate_disabled_lets_through(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MVP_SEGMENT_GATE_ENABLED", "false")
    get_settings.cache_clear()
    _enforce_mvp_segment_gate(_valid_profile(region="us", medical_conditions=["ckd"]))


def test_post_h2_diabetes_t1_only_remaining_block() -> None:
    """After H2 sweep, only diabetes_t1 is gated. Stacking with lifted
    conditions still raises but the message lists only the still-gated one."""
    p = _valid_profile(
        medical_conditions=["diabetes_t1", "ckd", "diabetes_t2", "hypertension"],
    )
    with pytest.raises(BusinessRuleViolation) as ei:
        _enforce_mvp_segment_gate(p)
    msg = str(ei.value)
    assert "diabetes_t1" in msg
    assert "ckd" not in msg
    assert "diabetes_t2" not in msg
    assert "hypertension" not in msg


def test_hypertension_alone_passes() -> None:
    _enforce_mvp_segment_gate(_valid_profile(medical_conditions=["hypertension"]))
