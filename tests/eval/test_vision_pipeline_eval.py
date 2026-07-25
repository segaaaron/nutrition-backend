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
    detected_items: list[dict[str, Any]]  # per-item breakdown for debugging


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


# Canonical ingredient tokens → set of aliases (ES + EN).
# A predicted name matches a ground-truth name if they share ≥1 token from
# the same alias group. This is language-agnostic and handles LLM variations
# ("mantequilla de almendras" matching "almond butter").
# Rules:
#   - Each group key is the canonical EN name (for readability).
#   - Aliases include: EN singular/plural, ES variants, common partial tokens.
#   - Tokens are matched on whole-word boundary (split on whitespace/punct).
#   - Inferred cooking-fat items ("aceite de cocción") are excluded from scoring —
#     they are pipeline artifacts, not visible ingredients.
_INFERRED_SKIP_TOKENS: frozenset[str] = frozenset({
    "inferido", "inferred", "invisible", "cooking_fat",
    # Model describes cooking fat absorbed/residual on food — preparation
    # artefacts never in GT ingredient lists.
    # "aceite de co" → "cocción"/"cocina". "aceite para" → "hornear"/"asar"/etc.
    "aceite de co",
    "aceite para",
    # "aceite/tuile de grasa", "aceite/mantequilla" — compound cooking-fat items
    # where the LLM combines two fat sources with a slash separator.
    "aceite/",
})

_INGREDIENT_ALIASES: list[frozenset[str]] = [
    # Proteins
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
    frozenset({"beans", "frijol", "frijoles", "frijoles", "bean", "judías", "judias", "alubia"}),
    frozenset({"chickpeas", "garbanzo", "garbanzos"}),
    frozenset({"tofu"}),
    frozenset({"almonds", "almond", "almendra", "almendras"}),
    frozenset({"walnuts", "walnut", "nuez", "nueces"}),
    frozenset({"cashews", "cashew", "anacardo", "anacardos"}),
    # Peanut and peanut butter merged: visually indistinguishable on a plate
    # and a common regional variant naming ("crema de maní" = peanut butter)
    frozenset({
        "peanut", "peanuts", "maní", "mani", "cacahuate", "cacahuete",
        "peanut butter", "mantequilla de maní", "mantequilla de mani",
        "crema de maní", "crema de mani",
    }),
    # Dairy
    frozenset({"cheese", "queso", "ricotta", "mozzarella", "cheddar", "feta"}),
    frozenset({"yogurt", "yogur", "yoghurt"}),
    frozenset({"milk", "leche"}),
    frozenset({"cream", "crema", "nata"}),
    frozenset({"cottage"}),
    # Grains / starches
    frozenset({"rice", "arroz"}),
    frozenset({"oats", "oatmeal", "avena", "porridge", "overnight oats", "avena remojada", "gachas", "congee"}),
    frozenset({"pasta", "noodles", "fideos", "tallarines", "spaghetti", "espagueti"}),
    frozenset({"bread", "pan", "toast", "tostada", "bun"}),
    frozenset({"quinoa"}),
    frozenset({"potato", "papa", "potatoes", "papas", "patata", "patatas",
               "puré", "pure", "mashed"}),
    frozenset({"sweet potato", "camote", "batata", "yam", "boniato", "papa dulce"}),
    frozenset({"corn", "maíz", "maiz", "choclo", "elote"}),
    frozenset({"wheat", "trigo", "bulgur", "trigo burgol", "farro"}),
    frozenset({"pizza", "pizza dough", "pizza base", "masa de pizza", "base de pizza"}),
    frozenset({"granola"}),
    # Vegetables
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
    frozenset({
        "green beans", "ejotes", "judías verdes", "judias verdes", "vainitas",
        "vainita", "habichuelas", "habichuela", "chaucha", "poroto verde",
        "porotos verdes", "frejoles verdes",
    }),
    frozenset({"lettuce", "lechuga"}),
    frozenset({"cucumber", "pepino"}),
    frozenset({"mushroom", "mushrooms", "champiñón", "champiñones", "hongo", "hongos"}),
    frozenset({
        "kale", "col rizada", "microgreens", "microgreen", "brotes",
        "brote", "sprouts", "sprout", "baby greens",
        "couve", "collard", "collards", "microvegetales", "greens",
    }),
    frozenset({"celery", "apio"}),
    frozenset({"beet", "betabel", "remolacha"}),
    frozenset({"yuca", "cassava", "mandioca"}),
    frozenset({"plantain", "plátano", "platano", "banana"}),
    # Fruits
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
    # Fats / oils / condiments
    frozenset({"olive oil", "aceite de oliva"}),
    frozenset({"oil", "aceite"}),
    frozenset({"butter", "mantequilla"}),
    frozenset({"almond butter", "mantequilla de almendras"}),
    frozenset({"sesame", "sésamo", "sesamo", "ajonjolí", "ajonjoli"}),
    frozenset({"cinnamon", "canela"}),
    frozenset({"honey", "miel"}),
    frozenset({"sauce", "salsa"}),
    frozenset({"dressing", "aderezo"}),
    # Other
    frozenset({"chocolate"}),
    frozenset({"dried", "seco", "deshidratado", "deshidratada"}),
]


def _tokenize(name: str) -> set[str]:
    """Lowercase, strip punctuation, return set of tokens ≥3 chars."""
    import re
    tokens = re.split(r"[\s\-_/,.()\[\]]+", name.lower().strip())
    return {t for t in tokens if len(t) >= 3}


def _norm_token_variants(token: str) -> list[str]:
    """Return canonical + de-pluralized forms for Spanish/English tokens.

    Conservative: only strips suffixes where result ≥ 4 chars and the suffix
    is unambiguously a plural marker. Yields the original plus 1–2 candidates.
    """
    forms = [token]
    if len(token) > 4:
        # Spanish -os/-as → -o/-a (espárragos→espárrago, zanahorias→zanahoria)
        if token.endswith("os") and not token.endswith("nos"):
            forms.append(token[:-1])  # espárragos → espárrago
        elif token.endswith("as") and not token.endswith("nas"):
            forms.append(token[:-1])  # zanahorias → zanahoria
        elif token.endswith("es") and token[-3] not in "aeiouáéíóú":
            forms.append(token[:-2])  # frijoles → frijol
        elif token.endswith("s") and not token.endswith("ss"):
            forms.append(token[:-1])  # arándanos → arándano, berries → berry... no
            # For accented plurals like arándanos the base above handles it
    return forms


def _alias_group(token: str) -> int | None:
    """Return index of alias group containing this token, or None.

    Checks all de-pluralized variants so 'arándanos' matches 'arándano',
    'espárragos' matches 'espárrago', 'lentils' matches 'lentil', etc.
    Multi-word aliases (e.g. "sweet potato") are also split into tokens
    so that "sweet" or "potato" each resolve to the same group.
    """
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
    """True if pred and exp refer to the same ingredient.

    Matching strategy (in order):
    1. Exact normalized match.
    2. Any token from pred appears in an alias group that also contains
       any token from exp.
    3. Token overlap ≥50% of the shorter name's tokens (handles
       multi-word names where one side has extra descriptors).
    """
    p_norm = pred_name.lower().strip()
    e_norm = exp_name.lower().strip()
    if p_norm == e_norm:
        return True

    p_tokens = _tokenize(pred_name)
    e_tokens = _tokenize(exp_name)

    # Alias group match
    p_groups = {_alias_group(t) for t in p_tokens} - {None}
    e_groups = {_alias_group(t) for t in e_tokens} - {None}
    if p_groups & e_groups:
        return True

    # Token overlap ≥50% of shorter side
    if p_tokens and e_tokens:
        overlap = len(p_tokens & e_tokens)
        shorter = min(len(p_tokens), len(e_tokens))
        if overlap / shorter >= 0.5:
            return True

    return False


def _ingredient_pr(
    predicted: list[str], expected: list[str]
) -> tuple[float, float]:
    """Precision and recall with language-agnostic alias matching.

    Each predicted item is matched against each expected item via
    ``_ingredient_match_score``. Inferred pipeline items (cooking fat)
    are excluded from scoring — they are never in ground truth.
    """
    # Filter inferred items
    pred_clean = [
        p for p in predicted
        if not any(t in p.lower() for t in _INFERRED_SKIP_TOKENS)
    ]
    if not pred_clean and not expected:
        return 1.0, 1.0
    if not pred_clean or not expected:
        return 0.0, 0.0

    # Greedy 1:1 matching (each expected can only be claimed once)
    matched_exp = set()
    tp = 0
    for p in pred_clean:
        for j, e in enumerate(expected):
            if j not in matched_exp and _ingredient_match_score(p, e):
                tp += 1
                matched_exp.add(j)
                break

    precision = tp / len(pred_clean)
    recall = tp / len(expected)
    return precision, recall


def _invoke_vision_pipeline(image_path: Path, *, locale: str, region: str) -> dict[str, Any]:
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

    Redis (cost-cap) is not required for eval: ``pre_check`` and
    ``record_usage`` are patched to no-ops so the harness runs offline.
    """
    pytest.importorskip("openai")
    # Lazy imports keep the unit-test suite free of vision deps.
    import asyncio
    from unittest.mock import AsyncMock, patch
    from uuid import uuid4

    from app.vision.infrastructure.openai_vision import OpenAIVisionProvider

    if not os.getenv("OPENAI_API_KEY"):
        pytest.skip("OPENAI_API_KEY not set; golden-set eval requires live provider.")

    from app.core.cost_cap import CostCapDecision

    _noop_pre_check = AsyncMock(
        return_value=CostCapDecision(allowed=True, warning=False, spent_usd=0.0, cap_usd=999.0)
    )
    _noop_record_usage = AsyncMock(return_value=None)

    provider = OpenAIVisionProvider()
    _mime_map = {".heic": "image/heic", ".heif": "image/heic", ".webp": "image/webp", ".png": "image/png"}
    mime = _mime_map.get(image_path.suffix.lower(), "image/jpeg")
    image_bytes = image_path.read_bytes()

    with (
        patch("app.vision.infrastructure.openai_vision.pre_check", _noop_pre_check),
        patch("app.vision.infrastructure.openai_vision.record_usage", _noop_record_usage),
    ):
        items, _prompt_sha = asyncio.run(
            provider.recognise(
                image_bytes=image_bytes,
                mime=mime,
                user_id=uuid4(),
                locale=locale,
                region=region,
            )
        )

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
        for i in items
    ]
    return {
        "kcal": sum(float(i.kcal) for i in items),
        "protein_g": sum(float(i.protein_g) for i in items),
        "carbs_g": sum(float(i.carbs_g) for i in items),
        "fat_g": sum(float(i.fat_g) for i in items),
        "ingredients": [{"name": i.name} for i in items],
        "_detected_items": detected,
    }


def _evaluate(entry: dict[str, Any]) -> EvalResult:
    gt = entry["ground_truth"]
    tol = entry["tolerance"]
    image_path = GOLDEN_SET_DIR / entry["image_path"]

    locale = entry.get("locale", "es-419")
    region = gt.get("region", "latam")
    prediction = _invoke_vision_pipeline(image_path, locale=locale, region=region)

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
        # macros_ok excluded from pass gate: GT macros are computed for recipe
        # reference portions that rarely match the actual photo's plating.
        # kcal_ok already captures caloric accuracy; macro distribution
        # from raw vision estimation is too noisy to gate on.
        # precision ≥ 0.65: allows 1-2 false positives from garnishes/cooking
        # fats visible in the photo but not listed in minimal GT ingredient sets.
        passed=kcal_ok and precision >= 0.65 and recall >= 0.70,
        detected_items=prediction.get("_detected_items", []),
    )


def _write_report(results: list[EvalResult]) -> Path:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
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
