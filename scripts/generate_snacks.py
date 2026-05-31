"""Snack catalog generator — bootstraps the snack inventory gap (spec §22.6).

Calls OpenAI (gpt-4o-mini by default) with the prompt structure from the
`.claude/agents/nova-clinical-nutrition-generator.md` agent (round-3 EN canonical).

Emits 4 categories (sweet, savory, high_protein, low_kcal), 25 each → 100 snacks.
Validates each via the same gates as `scripts/audit_catalog.py` (subset checks
inline here; full gates re-run via `audit_catalog.py` after dump).

Writes `data/meals/nova_snacks_v1.json`.

Cost cap: hard \$3.00. Aborts (no partial write) if estimate exceeds cap.

Usage:
    OPENAI_API_KEY=sk-... uv run python -m scripts.generate_snacks --batch 25 --total 100
    # Or sample run (no API call, deterministic):
    uv run python -m scripts.generate_snacks --sample 5

By default this script is INERT (writes a sample file). Real generation
requires --batch >= 1 plus OPENAI_API_KEY and explicit --confirm-cost.

TODO: when ready to spend ~\$1-3 OpenAI quota, run with --confirm-cost.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import secrets
import sys
from pathlib import Path

from app.core.logging import configure_logging, get_logger
from app.shared.domain.macro_tolerance import MACRO_TOLERANCE

log = get_logger("scripts.generate_snacks")

ROOT = Path(__file__).resolve().parent.parent
OUT_PATH = ROOT / "data" / "meals" / "nova_snacks_v1.json"
AGENT_PROMPT_PATH = ROOT / ".claude" / "agents" / "nova-clinical-nutrition-generator.md"

CATEGORIES = ["sweet", "savory", "high_protein", "low_kcal"]
DEFAULT_BATCH = 25
HARD_COST_CAP_USD = 3.00

VALID_ALLERGENS = {
    "dairy", "gluten", "tree_nuts", "peanuts", "shellfish", "fish", "egg",
    "soy", "sesame", "celery", "mustard", "lupin", "sulphites", "molluscs",
}
VALID_REGIONS = {"us", "ca", "eu", "uk", "latam"}
VALID_GOALS = {"weight_loss", "maintain", "muscle_gain", "weight_gain", "health"}


SAMPLE_SNACKS = [
    {
        "id": "nova_snack_sample_001",
        "name": "Yogur Griego con Arándanos y Almendras",
        "description": "Snack alto en proteína con calcio y antioxidantes; ideal para media tarde sin disparar la insulina.",
        "nutritionProfile": {"calories": 180, "macros": {"proteinG": 18, "carbsG": 14, "fatG": 6}},
        "matchingCriteria": {
            "targetGoals": ["weight_loss", "muscle_gain", "maintain"],
            "suitableForActivity": ["sedentary", "lightly_active", "moderately_active"],
            "recommendedForConditions": ["diabetes_t2", "overweight"],
            "contraindicatedConditions": ["lactose_intolerance"],
            "allergens": ["dairy", "tree_nuts"],
            "regions": ["us", "ca", "eu", "uk", "latam"],
        },
        "execution": {
            "mealTime": "snack",
            "prepTimeMinutes": 3,
            "firebaseImageUrl": None,
            "ingredients": [
                "170 g de yogur griego sin azúcar",
                "40 g de arándanos frescos",
                "10 g de almendras fileteadas",
            ],
            "instructions": [
                "Servir el yogur griego en un bowl.",
                "Añadir los arándanos y las almendras encima.",
                "Consumir frío.",
            ],
            "source_catalog": "nova_snacks_v1_sample",
        },
    },
    {
        "id": "nova_snack_sample_002",
        "name": "Hummus con Bastones de Zanahoria y Apio",
        "description": "Combinación de fibra y grasa monoinsaturada; mantiene la saciedad sin pico glucémico.",
        "nutritionProfile": {"calories": 150, "macros": {"proteinG": 5, "carbsG": 18, "fatG": 7}},
        "matchingCriteria": {
            "targetGoals": ["weight_loss", "maintain", "health"],
            "suitableForActivity": ["sedentary", "lightly_active"],
            "recommendedForConditions": ["hypertension", "dyslipidemia"],
            "contraindicatedConditions": [],
            "allergens": ["sesame", "celery"],
            "regions": ["us", "ca", "eu", "uk", "latam"],
        },
        "execution": {
            "mealTime": "snack",
            "prepTimeMinutes": 5,
            "firebaseImageUrl": None,
            "ingredients": [
                "80 g de hummus tradicional",
                "60 g de zanahoria en bastones",
                "40 g de apio en bastones",
            ],
            "instructions": [
                "Cortar la zanahoria y el apio en bastones.",
                "Servir el hummus en un cuenco y mojar los vegetales antes de consumir.",
            ],
            "source_catalog": "nova_snacks_v1_sample",
        },
    },
    {
        "id": "nova_snack_sample_003",
        "name": "Huevo Duro con Aguacate y Sal Marina",
        "description": "Snack denso en proteína completa y grasa saludable; saciante por 3-4 horas.",
        "nutritionProfile": {"calories": 220, "macros": {"proteinG": 12, "carbsG": 6, "fatG": 17}},
        "matchingCriteria": {
            "targetGoals": ["weight_loss", "muscle_gain", "maintain"],
            "suitableForActivity": ["lightly_active", "moderately_active", "very_active"],
            "recommendedForConditions": ["overweight", "pcos"],
            "contraindicatedConditions": [],
            "allergens": ["egg"],
            "regions": ["latam", "us", "eu"],
        },
        "execution": {
            "mealTime": "snack",
            "prepTimeMinutes": 10,
            "firebaseImageUrl": None,
            "ingredients": [
                "1 huevo entero duro",
                "60 g de aguacate maduro",
                "1 pizca de sal marina",
            ],
            "instructions": [
                "Cocer el huevo 9 minutos en agua hirviendo; enfriar y pelar.",
                "Cortar el aguacate en cubos.",
                "Espolvorear sal marina y consumir juntos.",
            ],
            "source_catalog": "nova_snacks_v1_sample",
        },
    },
    {
        "id": "nova_snack_sample_004",
        "name": "Manzana con Mantequilla de Maní Natural",
        "description": "Clásico balanceado: fibra soluble + grasa monoinsaturada + proteína vegetal.",
        "nutritionProfile": {"calories": 200, "macros": {"proteinG": 7, "carbsG": 24, "fatG": 9}},
        "matchingCriteria": {
            "targetGoals": ["maintain", "muscle_gain", "weight_gain"],
            "suitableForActivity": ["lightly_active", "moderately_active", "very_active"],
            "recommendedForConditions": ["athletic_load"],
            "contraindicatedConditions": [],
            "allergens": ["peanuts"],
            "regions": ["us", "ca", "eu", "uk", "latam"],
        },
        "execution": {
            "mealTime": "snack",
            "prepTimeMinutes": 2,
            "firebaseImageUrl": None,
            "ingredients": [
                "1 manzana mediana (150 g)",
                "16 g de mantequilla de maní natural sin azúcar",
            ],
            "instructions": [
                "Cortar la manzana en rodajas.",
                "Untar cada rodaja con un poco de mantequilla de maní.",
            ],
            "source_catalog": "nova_snacks_v1_sample",
        },
    },
    {
        "id": "nova_snack_sample_005",
        "name": "Pepino con Queso Cottage y Eneldo",
        "description": "Snack ultra-bajo en calorías, alto en proteína y volumen; ideal para déficit.",
        "nutritionProfile": {"calories": 90, "macros": {"proteinG": 11, "carbsG": 6, "fatG": 2}},
        "matchingCriteria": {
            "targetGoals": ["weight_loss", "maintain"],
            "suitableForActivity": ["sedentary", "lightly_active"],
            "recommendedForConditions": ["overweight", "obesity", "hypertension"],
            "contraindicatedConditions": ["lactose_intolerance"],
            "allergens": ["dairy"],
            "regions": ["us", "eu", "uk", "latam"],
        },
        "execution": {
            "mealTime": "snack",
            "prepTimeMinutes": 4,
            "firebaseImageUrl": None,
            "ingredients": [
                "150 g de pepino en rodajas",
                "80 g de queso cottage bajo en grasa",
                "1 pizca de eneldo fresco",
            ],
            "instructions": [
                "Cortar el pepino en rodajas gruesas.",
                "Colocar una cucharada de cottage sobre cada rodaja y espolvorear eneldo.",
            ],
            "source_catalog": "nova_snacks_v1_sample",
        },
    },
]


def _validate_record(rec: dict) -> list[str]:
    """Subset of audit_catalog.py gates that must hold per snack."""
    errs: list[str] = []
    nut = rec.get("nutritionProfile") or {}
    macros = nut.get("macros") or {}
    kcal = nut.get("calories", 0) or 0
    derived = macros.get("proteinG", 0) * 4 + macros.get("carbsG", 0) * 4 + macros.get("fatG", 0) * 9
    if kcal <= 0 or abs(kcal - derived) / kcal > MACRO_TOLERANCE:
        errs.append(f"gate2_macro_drift: kcal={kcal} derived={derived}")

    crit = rec.get("matchingCriteria") or {}
    allergens = crit.get("allergens") or []
    if any(a not in VALID_ALLERGENS for a in allergens):
        errs.append(f"gate3_unknown_allergen: {set(allergens) - VALID_ALLERGENS}")
    regions = crit.get("regions") or []
    if not regions or any(r not in VALID_REGIONS for r in regions):
        errs.append(f"gate8_invalid_regions: {regions}")
    goals = crit.get("targetGoals") or []
    if any(g not in VALID_GOALS for g in goals):
        errs.append(f"gate_goal_unknown: {set(goals) - VALID_GOALS}")
    meal_time = (rec.get("execution") or {}).get("mealTime")
    if meal_time != "snack":
        errs.append(f"meal_time_must_be_snack: got {meal_time!r}")
    return errs


async def _generate_batch(category: str, n: int, model: str) -> list[dict]:
    """Real OpenAI call. Returns list of n JSON snack records.

    The prompt is constructed from the agent's system prompt (loaded from
    .claude/agents/nova-clinical-nutrition-generator.md) plus a category hint.
    """
    from openai import AsyncOpenAI

    system_prompt = AGENT_PROMPT_PATH.read_text() if AGENT_PROMPT_PATH.exists() else ""
    user_prompt = (
        f"Generate exactly {n} unique SNACK recipes in the {category!r} category. "
        f"Each record MUST set execution.mealTime='snack' and regions=['us','ca','eu','uk','latam'] "
        f"unless culturally specific. Respond with a JSON array only — no prose."
    )

    client = AsyncOpenAI(api_key=os.environ["OPENAI_API_KEY"])
    resp = await client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        response_format={"type": "json_object"},
        temperature=0.85,
    )
    raw = resp.choices[0].message.content or ""
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        log.error("generate_snacks.json_parse_failed", category=category, raw=raw[:200])
        return []
    # Some completions wrap the array in {"snacks": [...]}; handle both.
    if isinstance(parsed, dict):
        for key in ("snacks", "recipes", "data", "items"):
            if key in parsed and isinstance(parsed[key], list):
                return parsed[key]
        return []
    return parsed if isinstance(parsed, list) else []


async def main() -> int:
    configure_logging()
    parser = argparse.ArgumentParser()
    parser.add_argument("--sample", type=int, default=0, help="Emit N sample snacks (no API call). Default 5 if --batch absent.")
    parser.add_argument("--batch", type=int, default=0, help="Snacks per category per OpenAI call.")
    parser.add_argument("--total", type=int, default=100)
    parser.add_argument("--model", default="gpt-4o-mini")
    parser.add_argument("--confirm-cost", action="store_true", help="Required to actually spend OpenAI dollars.")
    args = parser.parse_args()

    if args.batch == 0:
        # Sample mode (deterministic, no spend).
        n = args.sample or 5
        recs = SAMPLE_SNACKS[:n]
        errs_all: list[tuple[str, list[str]]] = []
        for r in recs:
            errs = _validate_record(r)
            if errs:
                errs_all.append((r["id"], errs))
        if errs_all:
            log.error("generate_snacks.sample_validation_failed", errors=errs_all)
            return 2
        OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        OUT_PATH.write_text(json.dumps(recs, ensure_ascii=False, indent=2))
        log.info("generate_snacks.sample_written", path=str(OUT_PATH), n=len(recs))
        log.info("generate_snacks.todo",
                 message="When ready to spend ~\\$1-3 OpenAI: "
                         "python -m scripts.generate_snacks --batch 25 --total 100 --confirm-cost")
        return 0

    if not args.confirm_cost:
        log.error("generate_snacks.refused_without_confirm_cost",
                  detail="Pass --confirm-cost to spend real OpenAI tokens.")
        return 2
    if not os.environ.get("OPENAI_API_KEY"):
        log.error("generate_snacks.no_api_key")
        return 2

    # Cost estimate guard. ~600 output tokens × n × $0.60/M (gpt-4o-mini out)
    est_usd = (args.total * 600 / 1_000_000) * 0.60 + (args.total * 1500 / 1_000_000) * 0.15
    if est_usd > HARD_COST_CAP_USD:
        log.error("generate_snacks.cost_cap_hit", estimate_usd=est_usd, cap_usd=HARD_COST_CAP_USD)
        return 2

    results: list[dict] = []
    per_cat = args.total // len(CATEGORIES)
    for cat in CATEGORIES:
        produced = 0
        while produced < per_cat:
            n = min(args.batch, per_cat - produced)
            batch = await _generate_batch(cat, n, args.model)
            for rec in batch:
                rec.setdefault("id", f"nova_snack_{secrets.token_hex(6)}")
                errs = _validate_record(rec)
                if errs:
                    log.warning("generate_snacks.record_invalid", id=rec.get("id"), errors=errs)
                    continue
                results.append(rec)
                produced += 1

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(results, ensure_ascii=False, indent=2))
    log.info("generate_snacks.complete", n=len(results), path=str(OUT_PATH))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
