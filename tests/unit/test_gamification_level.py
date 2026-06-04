"""Sprint 7.D — UserLevel curve (level n requires 100 * n^1.5 points)."""

from __future__ import annotations

from app.gamification.domain.entities import UserLevel


def test_zero_points_is_level_zero():
    ul = UserLevel.from_points(0)
    assert ul.level == 0
    assert ul.next_level_points == 100


def test_one_hundred_points_is_level_one():
    ul = UserLevel.from_points(100)
    assert ul.level == 1
    assert ul.next_level_points == int(100 * (2**1.5))


def test_curve_is_monotonic():
    pts = [0, 50, 100, 250, 500, 1000, 3162, 10000]
    levels = [UserLevel.from_points(p).level for p in pts]
    assert levels == sorted(levels)


def test_level_5_threshold():
    # 100 * 5^1.5 ≈ 1118 points to reach level 5
    ul = UserLevel.from_points(1200)
    assert ul.level >= 5
