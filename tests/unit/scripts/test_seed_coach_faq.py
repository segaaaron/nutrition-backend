"""Smoke tests for scripts/seed_coach_faq.py.

Validates: YAML loader shape, cost formatter, pgvector literal serialization.
No OpenAI calls, no DB writes — pure functions only.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from scripts.seed_coach_faq import (
    _format_cost,
    _load,
    _to_pgvector_literal,
)


def test_load_valid_yaml_returns_list_of_rows(tmp_path: Path) -> None:
    p = tmp_path / "faq.yaml"
    p.write_text(
        textwrap.dedent(
            """\
            - question_en: How much protein per kg?
              answers:
                en: ~1.6 g/kg for muscle building.
                es: ~1.6 g/kg para construir músculo.
              tags: [protein]
            - question_en: Sustainable deficit?
              answers:
                en: 15-25% below TDEE.
            """
        ),
        encoding="utf-8",
    )
    rows = _load(p)
    assert len(rows) == 2
    assert rows[0]["question_en"] == "How much protein per kg?"
    assert rows[0]["answers"]["en"].startswith("~1.6 g/kg")
    assert rows[1]["answers"]["en"].startswith("15-25%")


def test_load_missing_file_exits(tmp_path: Path) -> None:
    with pytest.raises(SystemExit) as exc:
        _load(tmp_path / "missing.yaml")
    assert exc.value.code == 2


def test_load_empty_yaml_exits(tmp_path: Path) -> None:
    p = tmp_path / "empty.yaml"
    p.write_text("[]\n", encoding="utf-8")
    with pytest.raises(SystemExit) as exc:
        _load(p)
    assert exc.value.code == 2


def test_load_row_missing_question_en_exits(tmp_path: Path) -> None:
    p = tmp_path / "bad.yaml"
    p.write_text("- answers: {en: x}\n", encoding="utf-8")
    with pytest.raises(SystemExit) as exc:
        _load(p)
    assert "question_en" in str(exc.value)


def test_load_row_missing_answers_en_exits(tmp_path: Path) -> None:
    p = tmp_path / "bad.yaml"
    p.write_text(
        textwrap.dedent(
            """\
            - question_en: Q
              answers: {es: only_spanish}
            """
        ),
        encoding="utf-8",
    )
    with pytest.raises(SystemExit) as exc:
        _load(p)
    assert "answers" in str(exc.value) or "en" in str(exc.value)


def test_format_cost_returns_human_readable_string() -> None:
    out = _format_cost(38)
    assert "38 rows" in out
    assert "tokens" in out
    assert "$" in out
    # Effectively free for tiny seeds: ≤ $0.001
    usd_part = out.rsplit("$", 1)[1]
    assert float(usd_part) < 0.001


def test_format_cost_scales_linearly() -> None:
    # 1000 rows produces a measurable USD that scales with row count.
    out = _format_cost(1000)
    usd = float(out.rsplit("$", 1)[1])
    assert usd > 0.0
    # Even 10k rows must stay under $0.10 — sanity ceiling for accidental large runs.
    big = _format_cost(10_000)
    big_usd = float(big.rsplit("$", 1)[1])
    assert big_usd < 0.10
    assert big_usd > usd


def test_to_pgvector_literal_matches_pgvector_format() -> None:
    vec = [0.1, -0.25, 1.0, 0.0]
    out = _to_pgvector_literal(vec)
    assert out.startswith("[") and out.endswith("]")
    parts = out[1:-1].split(",")
    assert len(parts) == 4
    assert parts[0] == "0.100000"
    assert parts[1] == "-0.250000"
    assert parts[2] == "1.000000"


def test_to_pgvector_literal_handles_empty_list() -> None:
    assert _to_pgvector_literal([]) == "[]"


def test_real_faq_seed_yaml_loads(tmp_path: Path) -> None:
    """Smoke: the actual data/coach/faq_seed.yaml must be loadable.

    Catches regressions if owner hand-edits the seed file and breaks shape.
    """
    repo_root = Path(__file__).resolve().parents[3]
    seed = repo_root / "data" / "coach" / "faq_seed.yaml"
    if not seed.exists():
        pytest.skip("faq_seed.yaml not present in this checkout")
    rows = _load(seed)
    assert len(rows) >= 10, f"FAQ catalog too small: {len(rows)} rows"
    for i, row in enumerate(rows):
        assert "question_en" in row, f"row {i} missing question_en"
        assert "answers" in row, f"row {i} missing answers"
        assert "en" in row["answers"], f"row {i} answers missing 'en'"
