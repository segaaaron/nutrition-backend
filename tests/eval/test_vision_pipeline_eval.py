"""Vision pipeline golden-set evaluation (item #31 skeleton).

Skipped by default. Enable with:

    RUN_GOLDEN_SET=true .venv/bin/python -m pytest tests/eval -m eval -v

Reads entries from ``docs/qa/golden_set/sample_entries.json`` (or
``entries.jsonl`` once curated to ≥100 platos), invokes the vision pipeline
per entry, computes per-entry pass/fail against declared tolerance, and
emits an aggregate JSON report to ``reports/golden_set/<timestamp>.json``.

This file is a SKELETON. The actual pipeline call is gated behind a
``pytest.importorskip`` so that the test suite remains importable even
when vision dependencies (or staging credentials) are absent.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
GOLDEN_SET_DIR = REPO_ROOT / "docs" / "qa" / "golden_set"
SAMPLE_ENTRIES = GOLDEN_SET_DIR / "sample_entries.json"
ENTRIES_JSONL = GOLDEN_SET_DIR / "entries.jsonl"
REPORT_DIR = REPO_ROOT / "reports" / "golden_set"

RUN_GOLDEN_SET = os.getenv("RUN_GOLDEN_SET", "").lower() in {"1", "true", "yes"}


pytestmark = [
    pytest.mark.eval,
    pytest.mark.skipif(
        not RUN_GOLDEN_SET,
        reason="Set RUN_GOLDEN_SET=true to execute vision golden-set eval.",
    ),
]


@dataclass(frozen=True)
class EvalResult:
    entry_id: str
    region: str
    meal_time: str
    kcal_expected: int
    kcal_actual: float
    kcal_within_tolerance: bool
    macros_within_tolerance: bool
    ingredients_precision: float
    ingredients_recall: float
    passed: bool


def _load_entries() -> list[dict[str, Any]]:
    """Load entries: prefer curated entries.jsonl, fall back to samples."""
    if ENTRIES_JSONL.exists():
        with ENTRIES_JSONL.open(encoding="utf-8") as fh:
            return [json.loads(line) for line in fh if line.strip()]
    if SAMPLE_ENTRIES.exists():
        with SAMPLE_ENTRIES.open(encoding="utf-8") as fh:
            return list(json.load(fh))
    pytest.skip("No golden set entries found.")
    return []  # unreachable, keeps mypy happy


def _within(actual: float, expected: float, pct: float) -> bool:
    """Return True when actual is within ±pct of expected."""
    if expected == 0:
        return actual == 0
    delta = abs(Decimal(str(actual)) - Decimal(str(expected))) / Decimal(str(expected))
    return delta <= Decimal(str(pct))


def _ingredient_pr(
    predicted: list[str], expected: list[str]
) -> tuple[float, float]:
    """Simple set-based precision and recall on ingredient names."""
    pred = {p.lower().strip() for p in predicted}
    exp = {e.lower().strip() for e in expected}
    if not pred and not exp:
        return 1.0, 1.0
    tp = len(pred & exp)
    precision = tp / len(pred) if pred else 0.0
    recall = tp / len(exp) if exp else 0.0
    return precision, recall


def _invoke_vision_pipeline(image_path: Path) -> dict[str, Any]:
    """Call the real OpenAI vision provider against one golden-set image.

    The full ``ProcessVisionJob`` orchestrator wires DB session + Redis +
    event bus + food matcher — none of which add signal to an *accuracy*
    eval. The accuracy of the cascade is determined by the provider
    output (kcal, macros, ingredient names), so this eval calls the
    provider directly and aggregates per-item totals into the dict shape
    expected by ``_evaluate``.

    Requires (gated by ``RUN_GOLDEN_SET`` env flag at module level):
      - ``OPENAI_API_KEY`` in env
      - libvips installed (Pillow loader works without it but the
        provider's pre-processor expects it for HEIC)
      - Network egress to api.openai.com
    """
    pytest.importorskip("openai")
    # Lazy imports keep the unit-test suite free of vision deps.
    import asyncio
    from uuid import uuid4

    from app.vision.infrastructure.openai_vision import OpenAIVisionProvider

    if not os.getenv("OPENAI_API_KEY"):
        pytest.skip("OPENAI_API_KEY not set; golden-set eval requires live provider.")

    provider = OpenAIVisionProvider()
    mime = "image/heic" if image_path.suffix.lower() in {".heic", ".heif"} else "image/jpeg"
    image_bytes = image_path.read_bytes()

    items, _prompt_sha = asyncio.run(
        provider.recognise(
            image_bytes=image_bytes,
            mime=mime,
            user_id=uuid4(),
            locale="es-PE",
            region="pe",
        )
    )

    return {
        "kcal": sum(float(i.kcal) for i in items),
        "protein_g": sum(float(i.protein_g) for i in items),
        "carbs_g": sum(float(i.carbs_g) for i in items),
        "fat_g": sum(float(i.fat_g) for i in items),
        "ingredients": [{"name": i.name} for i in items],
    }


def _evaluate(entry: dict[str, Any]) -> EvalResult:
    gt = entry["ground_truth"]
    tol = entry["tolerance"]
    image_path = GOLDEN_SET_DIR / entry["image_path"]

    prediction = _invoke_vision_pipeline(image_path)

    kcal_ok = _within(prediction["kcal"], gt["kcal"], tol["kcal_pct"])
    macros_ok = all(
        _within(prediction[m], gt[m], tol["macro_pct"])
        for m in ("protein_g", "carbs_g", "fat_g")
    )
    pred_names = [i["name"] for i in prediction.get("ingredients", [])]
    exp_names = [i["name"] for i in gt["ingredients"]]
    precision, recall = _ingredient_pr(pred_names, exp_names)

    return EvalResult(
        entry_id=entry["id"],
        region=gt["region"],
        meal_time=gt["meal_time"],
        kcal_expected=gt["kcal"],
        kcal_actual=float(prediction["kcal"]),
        kcal_within_tolerance=kcal_ok,
        macros_within_tolerance=macros_ok,
        ingredients_precision=precision,
        ingredients_recall=recall,
        passed=kcal_ok and macros_ok and precision >= 0.75 and recall >= 0.70,
    )


def _write_report(results: list[EvalResult]) -> Path:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = REPORT_DIR / f"vision_eval_{ts}.json"
    total = len(results)
    passed = sum(1 for r in results if r.passed)
    kcal_mae = (
        sum(abs(r.kcal_actual - r.kcal_expected) for r in results) / total
        if total
        else 0.0
    )
    payload = {
        "generated_at": ts,
        "total_entries": total,
        "passed": passed,
        "pass_rate": passed / total if total else 0.0,
        "kcal_mae": kcal_mae,
        "results": [asdict(r) for r in results],
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def test_vision_pipeline_golden_set() -> None:
    """Aggregate: ≥90% pass rate, ≤120 kcal MAE."""
    entries = _load_entries()
    results = [_evaluate(e) for e in entries]
    report_path = _write_report(results)

    pass_rate = sum(1 for r in results if r.passed) / len(results)
    kcal_mae = sum(abs(r.kcal_actual - r.kcal_expected) for r in results) / len(results)

    assert pass_rate >= 0.90, (
        f"Vision golden-set pass rate {pass_rate:.2%} below 90% threshold. "
        f"Report: {report_path}"
    )
    assert kcal_mae <= 120, (
        f"Vision golden-set kcal MAE {kcal_mae:.1f} above 120 kcal threshold. "
        f"Report: {report_path}"
    )
