"""Nutrient backfill: estimate sugar_g / sat_fat_g / fiber_g / sodium_mg for
ALL catalog recipes via gpt-4o-mini structured output.

WHY: the seeder left these four columns at their DDL default (0) for all
34,072 recipes. Condition gates (fatty_liver fiber>=3, diabetes_t2 sugar cap,
hypertension sodium cap, hypercholesterolemia sat-fat cap) either exclude the
ENTIRE catalog (any ">= floor" gate) or pass everything (any "<= cap" gate) —
both clinically wrong. Discovered 2026-06-10 when plan generation yielded
`plan_generation_yielded_no_meals` for a fatty_liver profile.

Input  : data/meals/nova_meals_catalog.json (name, ingredients with gram
         amounts, kcal/protein/carbs/fat) — rich context for estimation.
Output : data/meals/recipe_nutrient_mapping.json  {name: {sugar_g, sat_fat_g,
         fiber_g, sodium_mg}}
         scripts/sql/recipe_nutrient_update.sql   (UPDATE ... WHERE name_en=...)
Resume : .cache/nutrient_progress.json — saved every SAVE_EVERY recipes;
         re-run skips processed names.

Validation per row (estimates must be macro-coherent):
  0 <= sugar_g  <= carbs_g
  0 <= sat_fat_g <= fat_g
  0 <= fiber_g  <= carbs_g
  0 <= sodium_mg <= 4000
Out-of-bound values are clamped to the bound and counted in the final report.

Usage:
  .venv/bin/python scripts/nutrient_backfill.py --dry-run --limit 100
  .venv/bin/python scripts/nutrient_backfill.py --yes            # full run
Owner action after script finishes:
  psql $DATABASE_URL -f scripts/sql/recipe_nutrient_update.sql

Cost: ~34k calls x (~250 in + ~40 out) tokens on gpt-4o-mini ≈ $1.5-2.5 total.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
CATALOG_PATH = ROOT / "data/meals/nova_meals_catalog.json"
ENV_PATH = ROOT / ".env"
OUTPUT_MAPPING = ROOT / "data/meals/recipe_nutrient_mapping.json"
SQL_OUTPUT = ROOT / "scripts/sql/recipe_nutrient_update.sql"
PROGRESS_PATH = ROOT / ".cache/nutrient_progress.json"

MODEL = os.environ.get("NUTRIENT_BACKFILL_MODEL", "gpt-4o-mini")
CONCURRENCY = int(os.environ.get("NUTRIENT_BACKFILL_CONCURRENCY", "8"))
MAX_RETRIES = 3
SAVE_EVERY = 100
SODIUM_MAX = 4000

SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "sugar_g": {"type": "integer", "description": "total sugars, g per portion"},
        "sat_fat_g": {"type": "integer", "description": "saturated fat, g per portion"},
        "fiber_g": {"type": "integer", "description": "dietary fiber, g per portion"},
        "sodium_mg": {"type": "integer", "description": "sodium, mg per portion"},
    },
    "required": ["sugar_g", "sat_fat_g", "fiber_g", "sodium_mg"],
}

SYSTEM_PROMPT = (
    "Eres nutricionista experto en composición de alimentos (referencia USDA "
    "FoodData Central). Dada una receta con sus ingredientes en gramos y sus "
    "macros por porción, estima por porción: azúcares totales (g), grasa "
    "saturada (g), fibra dietética (g) y sodio (mg). Enteros, redondeo "
    "estándar. Coherencia obligatoria: sugar_g y fiber_g no pueden exceder "
    "los carbohidratos; sat_fat_g no puede exceder la grasa total. Si la "
    "receta no añade sal, estima solo el sodio intrínseco de los ingredientes."
)


def _load_env() -> dict[str, str]:
    env: dict[str, str] = {}
    if ENV_PATH.exists():
        for line in ENV_PATH.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def _load_progress() -> dict[str, dict[str, int]]:
    if PROGRESS_PATH.exists():
        return json.loads(PROGRESS_PATH.read_text())
    return {}


def _save_progress(done: dict[str, dict[str, int]]) -> None:
    PROGRESS_PATH.parent.mkdir(parents=True, exist_ok=True)
    PROGRESS_PATH.write_text(json.dumps(done, ensure_ascii=False))


def _user_prompt(rec: dict[str, Any]) -> str:
    np = rec.get("nutritionProfile", {})
    macros = np.get("macros", {})
    ingredients = rec.get("execution", {}).get("ingredients", [])
    return (
        f"Receta: {rec['name']}\n"
        f"Macros por porción: {np.get('calories')} kcal, "
        f"proteína {macros.get('proteinG')} g, "
        f"carbohidratos {macros.get('carbsG')} g, "
        f"grasa {macros.get('fatG')} g\n"
        f"Ingredientes: {'; '.join(ingredients) if ingredients else 'no listados'}"
    )


def _clamp(rec: dict[str, Any], est: dict[str, int], clamps: list[str]) -> dict[str, int]:
    macros = rec.get("nutritionProfile", {}).get("macros", {})
    carbs = int(macros.get("carbsG") or 0)
    fat = int(macros.get("fatG") or 0)
    out: dict[str, int] = {}
    bounds = {
        "sugar_g": carbs,
        "fiber_g": carbs,
        "sat_fat_g": fat,
        "sodium_mg": SODIUM_MAX,
    }
    for key, upper in bounds.items():
        v = int(est[key])
        if v < 0 or v > upper:
            clamps.append(f"{rec['name']}: {key}={v} -> [0,{upper}]")
            v = min(max(v, 0), upper)
        out[key] = v
    return out


async def _estimate_one(
    client: Any,
    sem: asyncio.Semaphore,
    rec: dict[str, Any],
    clamps: list[str],
) -> tuple[str, dict[str, int] | None]:
    async with sem:
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                resp = await client.chat.completions.create(
                    model=MODEL,
                    messages=[
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": _user_prompt(rec)},
                    ],
                    response_format={
                        "type": "json_schema",
                        "json_schema": {
                            "name": "nutrient_estimate",
                            "strict": True,
                            "schema": SCHEMA,
                        },
                    },
                    temperature=0.0,
                    max_tokens=80,
                )
                raw = json.loads(resp.choices[0].message.content or "{}")
                return rec["name"], _clamp(rec, raw, clamps)
            except Exception as exc:  # noqa: BLE001 — batch job: log, retry, then skip row
                if attempt == MAX_RETRIES:
                    print(f"[FAIL] {rec['name']}: {exc}", file=sys.stderr)
                    return rec["name"], None
                await asyncio.sleep(2 ** (attempt - 1))
    return rec["name"], None  # unreachable; satisfies type checkers


def _save_sql(mapping: dict[str, dict[str, int]]) -> None:
    SQL_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "-- NOVA recipe nutrient backfill — generated by nutrient_backfill.py",
        "-- Run: psql $DATABASE_URL -f scripts/sql/recipe_nutrient_update.sql",
        "-- Idempotent: re-running overwrites the four columns to latest mapping.",
        "-- Match key: name_en (34,072 unique names verified 2026-06-10).",
        "",
        "BEGIN;",
        "",
    ]
    for name, est in mapping.items():
        safe = name.replace("'", "''")
        lines.append(
            f"UPDATE recipes SET "
            f"sugar_g={est['sugar_g']}, "
            f"sat_fat_g={est['sat_fat_g']}, "
            f"fiber_g={est['fiber_g']}, "
            f"sodium_mg={est['sodium_mg']} "
            f"WHERE name_en='{safe}';"
        )
    lines += ["", "COMMIT;", ""]
    SQL_OUTPUT.write_text("\n".join(lines))


async def _run(args: argparse.Namespace) -> int:
    from openai import AsyncOpenAI

    env = _load_env()
    api_key = env.get("OPENAI_API_KEY") or os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        print("OPENAI_API_KEY missing (.env or environment).", file=sys.stderr)
        return 1

    catalog: list[dict[str, Any]] = json.loads(CATALOG_PATH.read_text())
    done = _load_progress()
    todo = [r for r in catalog if r["name"] not in done]
    if args.limit:
        todo = todo[: args.limit]

    print(f"catalog={len(catalog)} done={len(done)} todo={len(todo)} model={MODEL}")
    if not todo:
        _save_sql(done)
        print(f"Nothing to do. SQL regenerated at {SQL_OUTPUT.relative_to(ROOT)}")
        return 0
    if not args.dry_run and not args.yes:
        print("Full run spends ~$2 on OpenAI. Pass --yes to confirm, or --dry-run.")
        return 1

    client = AsyncOpenAI(api_key=api_key, timeout=30)
    sem = asyncio.Semaphore(CONCURRENCY)
    clamps: list[str] = []
    failed = 0

    for batch_start in range(0, len(todo), SAVE_EVERY):
        batch = todo[batch_start : batch_start + SAVE_EVERY]
        results = await asyncio.gather(
            *(_estimate_one(client, sem, r, clamps) for r in batch)
        )
        for name, est in results:
            if est is None:
                failed += 1
            else:
                done[name] = est
        if not args.dry_run:
            _save_progress(done)
        print(f"progress {min(batch_start + SAVE_EVERY, len(todo))}/{len(todo)}")

    if args.dry_run:
        sample = list(done.items())[-min(len(todo), 20) :]
        for name, est in sample:
            print(f"  {name[:60]:60s} {est}")
        print(f"\nDRY RUN — nothing persisted. clamped={len(clamps)} failed={failed}")
        for c in clamps[:10]:
            print(f"  clamp: {c}")
        return 0

    OUTPUT_MAPPING.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_MAPPING.write_text(json.dumps(done, ensure_ascii=False, indent=1))
    _save_sql(done)
    print(
        f"\nDone. estimated={len(done)} failed={failed} clamped={len(clamps)}\n"
        f"Owner action: psql $DATABASE_URL -f {SQL_OUTPUT.relative_to(ROOT)}"
    )
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--limit", type=int, default=0, help="process at most N recipes")
    p.add_argument("--dry-run", action="store_true", help="estimate + print, persist nothing")
    p.add_argument("--yes", action="store_true", help="confirm spending on full run")
    return asyncio.run(_run(p.parse_args()))


if __name__ == "__main__":
    sys.exit(main())
