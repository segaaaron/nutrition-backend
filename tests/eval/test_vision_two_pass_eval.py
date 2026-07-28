"""Vision two-pass pipeline golden-set evaluation.

Mirrors test_vision_pipeline_eval.py but exercises the ACTUAL production path:
    Call 1  provider.identify()  →  FoodIdentification list
    Call 2  provider.estimate()  →  PortionEstimate list
    Merge   RecognisePlate._merge()  →  DetectedFoodItem list
    Domain  decompose()  →  final items + totals

The single-pass eval (test_vision_pipeline_eval.py) calls provider.recognise()
which is a different code path.  Changes to ESTIMATE_SCHEMA or
_estimate_system_prompt are only validated by THIS harness.

Enable with:
    RUN_GOLDEN_SET=true OPENAI_API_KEY=sk-... \\
        .venv/bin/python -m pytest tests/eval/test_vision_two_pass_eval.py -m eval -v

Reads the same golden set as the single-pass eval:
    docs/qa/golden_set/sample_entries.json  (39 entries, images pre-downloaded)
    docs/qa/golden_set/entries.jsonl        (curated, takes precedence when present)

Emits report to:
    reports/golden_set/vision_twopass_eval_<timestamp>.json
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
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
        reason="Set RUN_GOLDEN_SET=true to execute vision two-pass golden-set eval.",
    ),
]


# ---------------------------------------------------------------------------
# Shared scoring helpers (duplicated from single-pass eval to keep files
# self-contained — no cross-file imports in eval suites).
# ---------------------------------------------------------------------------

_INFERRED_SKIP_TOKENS: frozenset[str] = frozenset({
    "inferido", "inferred", "invisible", "cooking_fat",
    "aceite de co", "aceite para", "aceite/",
})

_INGREDIENT_ALIASES: list[frozenset[str]] = [
    frozenset({"chicken", "pollo", "pechuga", "muslo"}),
    frozenset({"beef", "res", "carne", "ternera", "steak", "bistec"}),
    frozenset({"salmon", "salmón"}),
    frozenset({"cod", "bacalao"}),
    frozenset({"tilapia"}),
    frozenset({"tuna", "atún", "atun"}),
    frozenset({"shrimp", "camarón", "camaron", "langostino"}),
    frozenset({"egg", "huevo", "eggs", "huevos"}),
    frozenset({"turkey", "pavo"}),
    frozenset({"pork", "cerdo", "chancho"}),
    frozenset({"ham", "jamón", "jamon", "prosciutto", "serrano", "bacon", "tocino"}),
    frozenset({"lentils", "lenteja", "lentejas"}),
    frozenset({"beans", "frijol", "frijoles", "bean", "judías", "judias", "alubia"}),
    frozenset({"chickpeas", "garbanzo", "garbanzos"}),
    frozenset({"tofu"}),
    frozenset({"almonds", "almond", "almendra", "almendras"}),
    frozenset({"walnuts", "walnut", "nuez", "nueces"}),
    frozenset({"cashews", "cashew", "anacardo", "anacardos"}),
    frozenset({
        "peanut", "peanuts", "maní", "mani", "cacahuate", "cacahuete",
        "peanut butter", "mantequilla de maní", "mantequilla de mani",
        "crema de maní", "crema de mani",
    }),
    frozenset({"cheese", "queso", "ricotta", "mozzarella", "cheddar", "feta"}),
    frozenset({"yogurt", "yogur", "yoghurt"}),
    frozenset({"milk", "leche"}),
    frozenset({"cream", "crema", "nata"}),
    frozenset({"cottage"}),
    frozenset({"rice", "arroz"}),
    frozenset({"oats", "oatmeal", "avena", "porridge", "overnight oats", "avena remojada", "gachas", "congee"}),
    frozenset({"pasta", "noodles", "fideos", "tallarines", "spaghetti", "espagueti"}),
    frozenset({"bread", "pan", "toast", "tostada", "bun"}),
    frozenset({"quinoa"}),
    frozenset({"potato", "papa", "potatoes", "papas", "patata", "patatas", "puré", "pure", "mashed"}),
    frozenset({"sweet potato", "camote", "batata", "yam", "boniato", "papa dulce"}),
    frozenset({"corn", "maíz", "maiz", "choclo", "elote"}),
    frozenset({"wheat", "trigo", "bulgur", "trigo burgol", "farro"}),
    frozenset({"pizza", "pizza dough", "pizza base", "masa de pizza", "base de pizza"}),
    frozenset({"granola"}),
    frozenset({"spinach", "espinaca", "espinacas"}),
    frozenset({"broccoli", "brócoli", "brocoli"}),
    frozenset({"carrot", "carrots", "zanahoria", "zanahorias"}),
    frozenset({"tomato", "tomatoes", "tomate", "tomates", "jitomate"}),
    frozenset({"onion", "cebolla", "onions", "cebollas"}),
    frozenset({"garlic", "ajo"}),
    frozenset({"pepper", "peppers", "pimiento", "pimientos", "chile", "morrón", "morron", "jalapeño", "jalapeno", "jalapeños"}),
    frozenset({"zucchini", "calabacín", "calabacin", "calabacita"}),
    frozenset({"asparagus", "espárrago", "esparrago", "espárragos", "esparragos"}),
    frozenset({"cauliflower", "coliflor"}),
    frozenset({"green beans", "ejotes", "judías verdes", "judias verdes", "vainitas", "vainita", "habichuelas", "chaucha", "porotos verdes"}),
    frozenset({"lettuce", "lechuga"}),
    frozenset({"cucumber", "pepino"}),
    frozenset({"mushroom", "mushrooms", "champiñón", "champiñones", "hongo", "hongos"}),
    frozenset({"kale", "col rizada", "microgreens", "brotes", "sprouts", "baby greens", "couve", "collard", "greens"}),
    frozenset({"celery", "apio"}),
    frozenset({"beet", "betabel", "remolacha"}),
    frozenset({"yuca", "cassava", "mandioca"}),
    frozenset({"plantain", "plátano", "platano", "banana"}),
    frozenset({"apple", "manzana", "apples"}),
    frozenset({"mango"}),
    frozenset({"avocado", "aguacate", "palta"}),
    frozenset({"strawberry", "strawberries", "fresa", "fresas", "frutilla"}),
    frozenset({"blueberry", "blueberries", "arándano azul", "arandano azul", "arándano", "arandano"}),
    frozenset({"cranberry", "cranberries", "arándano rojo", "arandano rojo", "berries", "berry"}),
    frozenset({"orange", "naranja"}),
    frozenset({"lemon", "limón", "limon"}),
    frozenset({"peach", "durazno", "melocotón", "melocoton"}),
    frozenset({"grape", "grapes", "uva", "uvas"}),
    frozenset({"pineapple", "piña", "pina"}),
    frozenset({"olive oil", "aceite de oliva"}),
    frozenset({"oil", "aceite"}),
    frozenset({"butter", "mantequilla"}),
    frozenset({"almond butter", "mantequilla de almendras"}),
    frozenset({"sesame", "sésamo", "sesamo", "ajonjolí", "ajonjoli"}),
    frozenset({"cinnamon", "canela"}),
    frozenset({"honey", "miel"}),
    frozenset({"sauce", "salsa"}),
    frozenset({"dressing", "aderezo"}),
    frozenset({"chocolate"}),
    frozenset({"dried", "seco", "deshidratado", "deshidratada"}),
]


def _tokenize(name: str) -> set[str]:
    import re
    tokens = re.split(r"[\s\-_/,.()\[\]]+", name.lower().strip())
    return {t for t in tokens if len(t) >= 3}


def _norm_token_variants(token: str) -> list[str]:
    forms = [token]
    if len(token) > 4:
        if token.endswith("os") and not token.endswith("nos"):
            forms.append(token[:-1])
        elif token.endswith("as") and not token.endswith("nas"):
            forms.append(token[:-1])
        elif token.endswith("es") and token[-3] not in "aeiouáéíóú":
            forms.append(token[:-2])
        elif token.endswith("s") and not token.endswith("ss"):
            forms.append(token[:-1])
    return forms


def _alias_group(token: str) -> int | None:
    for norm in _norm_token_variants(token):
        for i, group in enumerate(_INGREDIENT_ALIASES):
            for alias in group:
                if alias == norm:
                    return i
                parts = alias.split()
                if len(parts) > 1 and norm in parts:
                    return i
    return None


def _ingredient_match_score(pred_name: str, exp_name: str) -> bool:
    p_norm = pred_name.lower().strip()
    e_norm = exp_name.lower().strip()
    if p_norm == e_norm:
        return True
    p_tokens = _tokenize(pred_name)
    e_tokens = _tokenize(exp_name)
    p_groups = {_alias_group(t) for t in p_tokens} - {None}
    e_groups = {_alias_group(t) for t in e_tokens} - {None}
    if p_groups & e_groups:
        return True
    if p_tokens and e_tokens:
        overlap = len(p_tokens & e_tokens)
        shorter = min(len(p_tokens), len(e_tokens))
        if overlap / shorter >= 0.5:
            return True
    return False


def _ingredient_pr(predicted: list[str], expected: list[str]) -> tuple[float, float]:
    pred_clean = [
        p for p in predicted
        if not any(t in p.lower() for t in _INFERRED_SKIP_TOKENS)
    ]
    if not pred_clean and not expected:
        return 1.0, 1.0
    if not pred_clean or not expected:
        return 0.0, 0.0
    matched_exp: set[int] = set()
    tp = 0
    for p in pred_clean:
        for j, e in enumerate(expected):
            if j not in matched_exp and _ingredient_match_score(p, e):
                tp += 1
                matched_exp.add(j)
                break
    return tp / len(pred_clean), tp / len(expected)


def _within(actual: float, expected: float, pct: float) -> bool:
    if expected == 0:
        return actual == 0
    delta = abs(Decimal(str(actual)) - Decimal(str(expected))) / Decimal(str(expected))
    return delta <= Decimal(str(pct))


# ---------------------------------------------------------------------------
# Two-pass pipeline invocation
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class TwoPassEvalResult:
    entry_id: str
    region: str
    meal_time: str | None
    kcal_expected: int
    kcal_actual: float
    kcal_within_tolerance: bool
    macros_within_tolerance: bool
    ingredients_precision: float
    ingredients_recall: float
    identification_conf_avg: float
    estimation_conf_avg: float
    degraded: bool
    passed: bool
    detected_items: list[dict[str, Any]]


def _load_entries() -> list[dict[str, Any]]:
    if ENTRIES_JSONL.exists():
        with ENTRIES_JSONL.open(encoding="utf-8") as fh:
            return [json.loads(line) for line in fh if line.strip()]
    if SAMPLE_ENTRIES.exists():
        with SAMPLE_ENTRIES.open(encoding="utf-8") as fh:
            return list(json.load(fh))
    pytest.skip("No golden set entries found.")
    return []


def _invoke_two_pass_pipeline(
    image_path: Path,
    *,
    locale: str,
    region: str,
    meal_time: str | None = None,
) -> dict[str, Any]:
    """Call the real two-pass pipeline against one golden-set image.

    Uses RecognisePlate (the production orchestrator) with:
    - OpenAIVisionProvider as both identifier and estimator
    - hint_source=None (no DB in eval context)
    - self_consistency_k=1 (single estimate run, cost-efficient for eval)
    - pre_check / record_usage patched to no-ops

    This exercises the exact path that changed:
        ESTIMATE_SCHEMA (size_category field)
        _estimate_system_prompt (synced anchors)
    """
    pytest.importorskip("openai")

    import asyncio
    from unittest.mock import AsyncMock, patch
    from uuid import uuid4

    from app.core.cost_cap import CostCapDecision
    from app.vision.application.recognise_plate import RecognisePlate, RecognitionContext
    from app.vision.domain.plate_decomposition import decompose
    from app.vision.infrastructure.openai_vision import OpenAIVisionProvider

    if not os.getenv("OPENAI_API_KEY"):
        pytest.skip("OPENAI_API_KEY not set; two-pass eval requires live provider.")

    _noop_pre_check = AsyncMock(
        return_value=CostCapDecision(allowed=True, warning=False, spent_usd=0.0, cap_usd=999.0)
    )
    _noop_record_usage = AsyncMock(return_value=None)

    provider = OpenAIVisionProvider()
    recogniser = RecognisePlate(
        identifier=provider,
        estimator=provider,
        hint_source=None,       # no DB in eval
        self_consistency_k=1,   # 1 estimate call — cost-efficient; use k=3 for production smoke
    )

    _mime_map = {".heic": "image/heic", ".heif": "image/heic", ".webp": "image/webp", ".png": "image/png"}
    mime = _mime_map.get(image_path.suffix.lower(), "image/jpeg")
    image_bytes = image_path.read_bytes()

    ctx = RecognitionContext(
        image_bytes=image_bytes,
        mime=mime,
        user_id=uuid4(),
        locale=locale,
        region=region,
        meal_time=meal_time,
    )

    with (
        patch("app.vision.infrastructure.openai_vision.pre_check", _noop_pre_check),
        patch("app.vision.infrastructure.openai_vision.record_usage", _noop_record_usage),
    ):
        outcome = asyncio.run(recogniser(ctx=ctx))

    items_list = list(outcome.items)

    # Domain post-pass — mirrors process_vision_job.py in production.
    items_list, _totals = decompose(items_list, slot=meal_time)

    detected = [
        {
            "name": i.name,
            "kcal": int(i.kcal),
            "protein_g": int(i.protein_g),
            "carbs_g": int(i.carbs_g),
            "fat_g": int(i.fat_g),
            "amount_g": float(i.estimated_amount_g),
            "food_group": i.food_group,
            "role": i.role,
            "prep_method": i.prep_method,
            "count": i.count,
            "inferred": i.inferred,
            "confidence": round(float(i.confidence), 2),
        }
        for i in items_list
    ]

    return {
        "kcal": sum(float(i.kcal) for i in items_list),
        "protein_g": sum(float(i.protein_g) for i in items_list),
        "carbs_g": sum(float(i.carbs_g) for i in items_list),
        "fat_g": sum(float(i.fat_g) for i in items_list),
        "ingredients": [{"name": i.name} for i in items_list],
        "identification_conf_avg": outcome.identification_conf_avg,
        "estimation_conf_avg": outcome.estimation_conf_avg,
        "degraded": outcome.degraded,
        "_detected_items": detected,
    }


def _evaluate(entry: dict[str, Any]) -> TwoPassEvalResult:
    gt = entry["ground_truth"]
    tol = entry["tolerance"]
    image_path = GOLDEN_SET_DIR / entry["image_path"]

    locale = entry.get("locale", "es-419")
    region = gt.get("region", "latam")
    meal_time = gt.get("meal_time")

    prediction = _invoke_two_pass_pipeline(
        image_path, locale=locale, region=region, meal_time=meal_time
    )

    kcal_ok = _within(prediction["kcal"], gt["kcal"], tol["kcal_pct"])
    macros_ok = all(
        _within(prediction[m], gt[m], tol["macro_pct"])
        for m in ("protein_g", "carbs_g", "fat_g")
    )
    pred_names = [i["name"] for i in prediction.get("ingredients", [])]
    exp_names = [i["name"] for i in gt["ingredients"]]
    precision, recall = _ingredient_pr(pred_names, exp_names)

    return TwoPassEvalResult(
        entry_id=entry["id"],
        region=gt["region"],
        meal_time=gt.get("meal_time"),
        kcal_expected=gt["kcal"],
        kcal_actual=float(prediction["kcal"]),
        kcal_within_tolerance=kcal_ok,
        macros_within_tolerance=macros_ok,
        ingredients_precision=precision,
        ingredients_recall=recall,
        identification_conf_avg=prediction.get("identification_conf_avg", 0.0),
        estimation_conf_avg=prediction.get("estimation_conf_avg", 0.0),
        degraded=prediction.get("degraded", False),
        passed=kcal_ok and precision >= 0.65 and recall >= 0.70,
        detected_items=prediction.get("_detected_items", []),
    )


def _write_report(results: list[TwoPassEvalResult]) -> Path:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    path = REPORT_DIR / f"vision_twopass_eval_{ts}.json"
    total = len(results)
    passed = sum(1 for r in results if r.passed)
    kcal_mae = (
        sum(abs(r.kcal_actual - r.kcal_expected) for r in results) / total
        if total else 0.0
    )
    n_degraded = sum(1 for r in results if r.degraded)
    avg_id_conf = sum(r.identification_conf_avg for r in results) / total if total else 0.0
    avg_est_conf = sum(r.estimation_conf_avg for r in results) / total if total else 0.0

    payload = {
        "generated_at": ts,
        "pipeline": "two_pass",
        "total_entries": total,
        "passed": passed,
        "pass_rate": passed / total if total else 0.0,
        "kcal_mae": kcal_mae,
        "degraded_count": n_degraded,
        "avg_identification_conf": round(avg_id_conf, 3),
        "avg_estimation_conf": round(avg_est_conf, 3),
        "results": [asdict(r) for r in results],
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Test entry point
# ---------------------------------------------------------------------------

def test_vision_two_pass_golden_set() -> None:
    """Two-pass pipeline: ≥90% pass rate, ≤120 kcal MAE, ≤10% degraded.

    Thresholds match the single-pass eval so the two files form a regression
    pair — any prompt/schema change that degrades accuracy fails BOTH.

    Degradation rate ≤10%: Call 2 (estimate) must succeed for ≥90% of entries.
    A high degradation rate signals that ESTIMATE_SCHEMA or the estimate prompt
    is causing upstream failures (empty response, parse error, cost cap).
    """
    entries = _load_entries()
    entries = [e for e in entries if (GOLDEN_SET_DIR / e["image_path"]).exists()]
    if not entries:
        pytest.skip("No golden-set images present on disk. Run download_images.py first.")

    results = [_evaluate(e) for e in entries]
    report_path = _write_report(results)

    total = len(results)
    pass_rate = sum(1 for r in results if r.passed) / total
    kcal_mae = sum(abs(r.kcal_actual - r.kcal_expected) for r in results) / total
    degraded_rate = sum(1 for r in results if r.degraded) / total

    assert degraded_rate <= 0.10, (
        f"Two-pass degradation rate {degraded_rate:.2%} above 10% — "
        f"Call 2 (estimate) failing too often. Report: {report_path}"
    )
    assert pass_rate >= 0.90, (
        f"Two-pass golden-set pass rate {pass_rate:.2%} below 90% threshold. "
        f"Report: {report_path}"
    )
    assert kcal_mae <= 120, (
        f"Two-pass golden-set kcal MAE {kcal_mae:.1f} above 120 kcal threshold. "
        f"Report: {report_path}"
    )
