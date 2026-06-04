"""Ranking signals for the plan-generation pipeline.

Each signal implements `app.plan.domain.ports.RankingSignal` and emits a
Decimal score in [0, 1]. Pure domain. Zero I/O. Zero framework imports.
"""

from __future__ import annotations
