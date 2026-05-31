"""Catalog audit pipeline — 8 ordered data-quality gates.

Run before any `seed_recipes.py` invocation. Produces a structured JSON
report at `reports/catalog_audit_<ts>.json` and exits non-zero on the first
hard-fail gate.

See spec §20 and `docs/superpowers/specs/2026-05-30-catalog-ingest-pipeline.md`.
Round-3 update: identifiers are EN canonical; allergen vocabulary is the
14-item US+EU superset (ADR-0001 round-3 + ADR-0008); conditions are EN
canonical (ADR-0001 Appendix A round-3); recipes carry `regions[]` (ADR-0008).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import statistics
import sys
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Single source of truth — keep aligned with app/shared/domain/macro_tolerance.py.
MACRO_TOLERANCE = 0.02

# Round-3 closed enums.
ALLERGEN_ENUM: frozenset[str] = frozenset(
    {
        "dairy", "gluten", "tree_nuts", "peanuts", "shellfish", "fish",
        "egg", "soy", "sesame",
        "celery", "mustard", "lupin", "sulphites", "molluscs",
    }
)

CANONICAL_CONDITIONS: frozenset[str] = frozenset(
    {
        "diabetes_t1", "diabetes_t2", "hypertension", "dyslipidemia",
        "hypercholesterolemia", "hypothyroidism", "hyperthyroidism", "ibs",
        "ibd", "celiac", "lactose_intolerance", "obesity", "overweight",
        "pregnancy", "lactation", "athletic_load", "ckd",
        "ischemic_heart_disease", "fatty_liver", "iron_deficiency_anemia",
        "pcos", "gout", "vitamin_d_deficiency", "chronic_insomnia",
        "mild_depression",
    }
)

MEAL_TIMES: frozenset[str] = frozenset({"breakfast", "lunch", "dinner", "snack"})

REGIONS: frozenset[str] = frozenset({"us", "ca", "eu", "uk", "latam"})

PLACEHOLDER_IMAGE_URL = "https://storage.googleapis.com/tu-proyecto/placeholder.webp"
ALLOWED_IMAGE_HOSTS = frozenset({"storage.googleapis.com", "cdn.nova-nutrition.com"})

# --- Condition synonym table (≥ 30 mappings) ---
# Maps upstream LLM-emitted / round-2 ES tokens → canonical EN ids.
CONDITION_SYNONYMS: dict[str, str] = {
    # English variants
    "diabetes": "diabetes_t2",
    "diabetes_type_1": "diabetes_t1",
    "diabetes_type_2": "diabetes_t2",
    "type_1_diabetes": "diabetes_t1",
    "type_2_diabetes": "diabetes_t2",
    "high_blood_pressure": "hypertension",
    "high_cholesterol": "hypercholesterolemia",
    "low_thyroid": "hypothyroidism",
    "underactive_thyroid": "hypothyroidism",
    "overactive_thyroid": "hyperthyroidism",
    "irritable_bowel_syndrome": "ibs",
    "irritable_bowel": "ibs",
    "inflammatory_bowel_disease": "ibd",
    "crohns": "ibd",
    "crohn_disease": "ibd",
    "ulcerative_colitis": "ibd",
    "celiac_disease": "celiac",
    "coeliac": "celiac",
    "coeliac_disease": "celiac",
    "lactose_intolerant": "lactose_intolerance",
    "obese": "obesity",
    "pregnant": "pregnancy",
    "breastfeeding": "lactation",
    "nursing": "lactation",
    "athlete": "athletic_load",
    "athletic_performance": "athletic_load",
    "athleticism": "athletic_load",
    "chronic_kidney_disease": "ckd",
    "kidney_disease": "ckd",
    "renal_disease": "ckd",
    "renal_insufficiency": "ckd",
    "cardiovascular_disease": "ischemic_heart_disease",
    "cardiovascular_health": "ischemic_heart_disease",
    "cardiovascular_disease_prevention": "ischemic_heart_disease",
    "heart_disease": "ischemic_heart_disease",
    "cardiopathy": "ischemic_heart_disease",
    "nafld": "fatty_liver",
    "non_alcoholic_fatty_liver": "fatty_liver",
    "hepatic_steatosis": "fatty_liver",
    "anemia": "iron_deficiency_anemia",
    "iron_anemia": "iron_deficiency_anemia",
    "polycystic_ovary_syndrome": "pcos",
    "polycystic_ovary": "pcos",
    "vitamin_d_low": "vitamin_d_deficiency",
    "low_vitamin_d": "vitamin_d_deficiency",
    "insomnia": "chronic_insomnia",
    "depression": "mild_depression",
    # Round-2 ES tokens (legacy)
    "hipertension": "hypertension",
    "dislipidemia": "dyslipidemia",
    "hipercolesterolemia": "hypercholesterolemia",
    "hipotiroidismo": "hypothyroidism",
    "hipertiroidismo": "hyperthyroidism",
    "sii": "ibs",
    "eii": "ibd",
    "celiaca": "celiac",
    "intolerancia_lactosa": "lactose_intolerance",
    "obesidad": "obesity",
    "sobrepeso": "overweight",
    "embarazo": "pregnancy",
    "lactancia": "lactation",
    "atletismo": "athletic_load",
    "ercc": "ckd",
    "cardiopatia": "ischemic_heart_disease",
    "higado_graso": "fatty_liver",
    "anemia_ferropenica": "iron_deficiency_anemia",
    "sop": "pcos",
    "gota": "gout",
    "deficit_vitamina_d": "vitamin_d_deficiency",
    "insomnio_cronico": "chronic_insomnia",
    "depresion_leve": "mild_depression",
}

# Allergen synonyms.
ALLERGEN_SYNONYMS: dict[str, str] = {
    "milk": "dairy",
    "lactose": "dairy",
    "wheat": "gluten",
    "nuts": "tree_nuts",
    "peanut": "peanuts",
    "shrimp": "shellfish",
    "crustaceans": "shellfish",
    "eggs": "egg",
    "soybeans": "soy",
    "soya": "soy",
    "sesame_seeds": "sesame",
    "sulphite": "sulphites",
    "sulfite": "sulphites",
    "sulfites": "sulphites",
    "mollusc": "molluscs",
    "mollusks": "molluscs",
}


# --- Ingredient → allergen lexicon (≥ 50 mappings, multi-locale words) ---
INGREDIENT_ALLERGEN_LEXICON: dict[str, str] = {
    # dairy (es+en+pt)
    "leche": "dairy", "lacteo": "dairy", "queso": "dairy", "yogur": "dairy",
    "yogurt": "dairy", "mantequilla": "dairy", "crema": "dairy",
    "requeson": "dairy", "ricotta": "dairy", "mozzarella": "dairy",
    "parmesano": "dairy", "cheddar": "dairy", "feta": "dairy", "suero": "dairy",
    "milk": "dairy", "cheese": "dairy", "butter": "dairy", "cream": "dairy",
    "kefir": "dairy", "ghee": "dairy", "leite": "dairy", "queijo": "dairy",
    # gluten
    "trigo": "gluten", "harina": "gluten", "pan": "gluten", "pasta": "gluten",
    "fideo": "gluten", "tallarin": "gluten", "espagueti": "gluten",
    "bagel": "gluten", "cuscus": "gluten", "bulgur": "gluten", "seitan": "gluten",
    "cebada": "gluten", "centeno": "gluten", "malta": "gluten",
    "wheat": "gluten", "bread": "gluten", "flour": "gluten", "barley": "gluten",
    "rye": "gluten", "spaghetti": "gluten", "noodle": "gluten",
    # tree_nuts
    "almendra": "tree_nuts", "nuez": "tree_nuts", "pistacho": "tree_nuts",
    "avellana": "tree_nuts", "anacardo": "tree_nuts", "maranon": "tree_nuts",
    "castana": "tree_nuts", "brasil": "tree_nuts", "macadamia": "tree_nuts",
    "pinon": "tree_nuts", "pecana": "tree_nuts",
    "almond": "tree_nuts", "walnut": "tree_nuts", "pistachio": "tree_nuts",
    "hazelnut": "tree_nuts", "cashew": "tree_nuts", "pecan": "tree_nuts",
    # peanuts
    "mani": "peanuts", "cacahuate": "peanuts", "cacahuete": "peanuts",
    "peanut": "peanuts",
    # shellfish
    "camaron": "shellfish", "langostino": "shellfish", "langosta": "shellfish",
    "cangrejo": "shellfish", "shrimp": "shellfish", "lobster": "shellfish",
    "crab": "shellfish", "prawn": "shellfish",
    # fish
    "salmon": "fish", "atun": "fish", "anchoa": "fish", "sardina": "fish",
    "bacalao": "fish", "merluza": "fish", "trucha": "fish", "tilapia": "fish",
    "pescado": "fish", "tuna": "fish", "cod": "fish", "anchovy": "fish",
    "sardine": "fish", "trout": "fish", "fish": "fish",
    # molluscs
    "mejillon": "molluscs", "almeja": "molluscs", "ostion": "molluscs",
    "ostra": "molluscs", "calamar": "molluscs", "pulpo": "molluscs",
    "vieira": "molluscs", "mussel": "molluscs", "clam": "molluscs",
    "oyster": "molluscs", "squid": "molluscs", "octopus": "molluscs",
    # egg
    "huevo": "egg", "clara": "egg", "yema": "egg", "mayonesa": "egg",
    "egg": "egg", "mayonnaise": "egg",
    # soy
    "soja": "soy", "soya": "soy", "tofu": "soy", "edamame": "soy",
    "tempeh": "soy", "miso": "soy", "tamari": "soy",
    # sesame
    "sesamo": "sesame", "ajonjoli": "sesame", "tahini": "sesame",
    "tahin": "sesame", "gomashio": "sesame", "sesame": "sesame",
    # celery
    "apio": "celery", "celery": "celery",
    # mustard
    "mostaza": "mustard", "mustard": "mustard",
    # lupin
    "altramuz": "lupin", "lupin": "lupin", "lupino": "lupin",
    # sulphites (commonly added to dried fruit / wine — minor catalog signal)
    "vino": "sulphites", "wine": "sulphites",
}

# Purine-heavy ingredients (gout risk flag — non-allergen).
PURINE_HEAVY_INGREDIENTS: frozenset[str] = frozenset(
    {"salmon", "atun", "tuna", "sardina", "sardine", "anchoa", "anchovy",
     "vísceras", "viscera", "higado", "liver", "rinon", "kidney",
     "mariscos", "shellfish", "shrimp", "camaron"}
)


# --- Data classes ---
@dataclass
class GateResult:
    gate: int
    name: str
    severity: str   # 'info' | 'warn' | 'fail'
    record_id: str | None
    message: str
    context: dict[str, Any] = field(default_factory=dict)


@dataclass
class AuditReport:
    catalog_path: str
    catalog_sha256: str
    started_at: str
    finished_at: str
    total_records: int
    gates_summary: dict[str, dict[str, int]]
    results: list[GateResult]
    passed: bool


# --- Helpers ---
_PUNCT_RE = re.compile(r"[^\w\s]", re.UNICODE)


def normalise(s: str) -> str:
    s = unicodedata.normalize("NFKD", s.lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = _PUNCT_RE.sub(" ", s)
    return re.sub(r"\s+", " ", s).strip()


def levenshtein(a: str, b: str) -> int:
    if a == b:
        return 0
    if len(a) < len(b):
        a, b = b, a
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        curr = [i] + [0] * len(b)
        for j, cb in enumerate(b, 1):
            curr[j] = min(prev[j] + 1, curr[j - 1] + 1, prev[j - 1] + (ca != cb))
        prev = curr
    return prev[-1]


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def get_field(rec: dict[str, Any], *path: str, default: Any = None) -> Any:
    cur: Any = rec
    for k in path:
        if not isinstance(cur, dict) or k not in cur:
            return default
        cur = cur[k]
    return cur


# --- Gate implementations ---
REQUIRED_TOP_KEYS = ("id", "name", "nutritionProfile", "matchingCriteria", "execution")


def gate_1_schema(records: list[dict[str, Any]]) -> list[GateResult]:
    out: list[GateResult] = []
    for rec in records:
        rid = rec.get("id") or "<missing_id>"
        for key in REQUIRED_TOP_KEYS:
            if key not in rec:
                out.append(GateResult(1, "json_schema", "fail", rid,
                                      f"missing top-level key '{key}'",
                                      {"missing": key}))
        np = get_field(rec, "nutritionProfile", default={})
        macros = get_field(np, "macros", default={})
        if "calories" not in np:
            out.append(GateResult(1, "json_schema", "fail", rid,
                                  "nutritionProfile.calories missing"))
        for m in ("proteinG", "carbsG", "fatG"):
            if m not in macros:
                out.append(GateResult(1, "json_schema", "fail", rid,
                                      f"nutritionProfile.macros.{m} missing"))
        if "mealTime" not in rec.get("execution", {}):
            out.append(GateResult(1, "json_schema", "fail", rid,
                                  "execution.mealTime missing"))
    return out


def gate_2_macros(records: list[dict[str, Any]]) -> list[GateResult]:
    out: list[GateResult] = []
    for rec in records:
        rid = rec.get("id") or "<unknown>"
        kcal = get_field(rec, "nutritionProfile", "calories")
        p = get_field(rec, "nutritionProfile", "macros", "proteinG")
        c = get_field(rec, "nutritionProfile", "macros", "carbsG")
        g = get_field(rec, "nutritionProfile", "macros", "fatG")
        if None in (kcal, p, c, g) or kcal <= 0:
            continue  # gate 1 already flagged
        derived = p * 4 + c * 4 + g * 9
        rel = abs(kcal - derived) / kcal
        if rel > MACRO_TOLERANCE:
            out.append(GateResult(2, "macro_consistency", "fail", rid,
                                  f"|kcal - derived|/kcal = {rel:.4f} > {MACRO_TOLERANCE}",
                                  {"kcal": kcal, "derived": derived, "rel": round(rel, 4)}))
    return out


def gate_3_allergens(records: list[dict[str, Any]]) -> list[GateResult]:
    out: list[GateResult] = []
    for rec in records:
        rid = rec.get("id") or "<unknown>"
        allergens = get_field(rec, "matchingCriteria", "allergens", default=[]) or []
        for a in allergens:
            normalised = ALLERGEN_SYNONYMS.get(a, a)
            if normalised not in ALLERGEN_ENUM:
                out.append(GateResult(3, "allergen_taxonomy", "fail", rid,
                                      f"allergen '{a}' not in 14-item closed enum",
                                      {"value": a}))
    return out


def gate_4_conditions(records: list[dict[str, Any]]) -> list[GateResult]:
    out: list[GateResult] = []
    for rec in records:
        rid = rec.get("id") or "<unknown>"
        rec_conds = get_field(rec, "matchingCriteria",
                              "recommendedForConditions", default=[]) or []
        ci_conds = get_field(rec, "matchingCriteria",
                             "contraindicatedConditions", default=[]) or []
        for cond in rec_conds + ci_conds:
            canon = CONDITION_SYNONYMS.get(cond, cond)
            if canon not in CANONICAL_CONDITIONS:
                # also tolerate already-canonical
                if cond in CANONICAL_CONDITIONS:
                    continue
                out.append(GateResult(4, "condition_vocab", "fail", rid,
                                      f"condition '{cond}' not in canonical set",
                                      {"value": cond}))
        # Disjointness: allergens MUST NOT appear in condition arrays.
        leaked = (set(rec_conds) | set(ci_conds)) & (
            ALLERGEN_ENUM | set(ALLERGEN_SYNONYMS.keys())
        )
        if leaked:
            out.append(GateResult(4, "condition_vocab", "fail", rid,
                                  "allergen tokens leaked into conditions",
                                  {"leaked": sorted(leaked)}))
    return out


def _collect_expected_allergens(ingredients: list[str]) -> set[str]:
    expected: set[str] = set()
    for raw in ingredients:
        norm = normalise(raw)
        for token in norm.split():
            if token in INGREDIENT_ALLERGEN_LEXICON:
                expected.add(INGREDIENT_ALLERGEN_LEXICON[token])
    return expected


def gate_5_allergen_completeness(records: list[dict[str, Any]]) -> list[GateResult]:
    out: list[GateResult] = []
    for rec in records:
        rid = rec.get("id") or "<unknown>"
        ings = get_field(rec, "execution", "ingredients", default=[]) or []
        declared_raw = get_field(rec, "matchingCriteria", "allergens", default=[]) or []
        declared = {ALLERGEN_SYNONYMS.get(a, a) for a in declared_raw}
        expected = _collect_expected_allergens(ings)
        missing = expected - declared
        if missing:
            out.append(GateResult(5, "allergen_completeness", "fail", rid,
                                  f"ingredient lexicon missing allergens: {sorted(missing)}",
                                  {"missing": sorted(missing),
                                   "declared": sorted(declared)}))
    return out


def gate_6_duplicates(records: list[dict[str, Any]]) -> list[GateResult]:
    out: list[GateResult] = []
    normed = [(r.get("id"), normalise(r.get("name", "")),
               get_field(r, "execution", "mealTime")) for r in records]
    # Group by normalised name + meal_time for exact-dupe fail; then sweep
    # distance ≤ 2 across full corpus for warn entries.
    groups: dict[tuple[str, str], list[str]] = defaultdict(list)
    for rid, n, mt in normed:
        groups[(n, mt)].append(rid)
    for (n, mt), ids in groups.items():
        if len(ids) > 1:
            out.append(GateResult(6, "duplicate_detection", "fail",
                                  ids[0],
                                  f"exact duplicate of {ids[1:]}",
                                  {"name_norm": n, "meal_time": mt, "ids": ids}))
    # Distance 1-2 sweep — warn only (skip if catalog > 5k for cost).
    if len(normed) <= 3000:
        seen_pairs = set()
        for i, (rid_a, na, _) in enumerate(normed):
            for j in range(i + 1, len(normed)):
                rid_b, nb, _ = normed[j]
                if abs(len(na) - len(nb)) > 2:
                    continue
                d = levenshtein(na, nb)
                if 0 < d <= 2:
                    key = tuple(sorted((rid_a, rid_b)))
                    if key in seen_pairs:
                        continue
                    seen_pairs.add(key)
                    out.append(GateResult(6, "duplicate_detection", "warn",
                                          rid_a, f"near-duplicate of {rid_b} (lev={d})",
                                          {"distance": d, "other": rid_b}))
    return out


def gate_7_outliers(records: list[dict[str, Any]]) -> list[GateResult]:
    out: list[GateResult] = []
    by_meal: dict[str, list[tuple[str, int]]] = defaultdict(list)
    for r in records:
        kcal = get_field(r, "nutritionProfile", "calories")
        mt = get_field(r, "execution", "mealTime")
        if kcal and mt:
            by_meal[mt].append((r.get("id"), kcal))
    for mt, items in by_meal.items():
        if len(items) < 5:
            continue
        kcals = [k for _, k in items]
        mean = statistics.mean(kcals)
        stdev = statistics.pstdev(kcals) or 1.0
        for rid, k in items:
            z = (k - mean) / stdev
            if abs(z) > 4:
                out.append(GateResult(7, "outlier_kcal", "fail", rid,
                                      f"kcal={k} z={z:.2f} for meal_time={mt}",
                                      {"kcal": k, "z": round(z, 2),
                                       "meal_time": mt}))
    return out


def gate_8_image_urls(records: list[dict[str, Any]]) -> list[GateResult]:
    out: list[GateResult] = []
    for rec in records:
        rid = rec.get("id") or "<unknown>"
        url = get_field(rec, "execution", "firebaseImageUrl")
        if url is None or url == "":
            continue
        if url == PLACEHOLDER_IMAGE_URL:
            out.append(GateResult(8, "image_url", "info", rid,
                                  "placeholder image URL (will null on --apply-fixes)",
                                  {"url": url}))
            continue
        if not url.startswith("https://"):
            out.append(GateResult(8, "image_url", "fail", rid,
                                  "non-https image URL",
                                  {"url": url}))
            continue
        host = url.split("/")[2] if "//" in url else ""
        if host not in ALLOWED_IMAGE_HOSTS:
            out.append(GateResult(8, "image_url", "fail", rid,
                                  f"image host {host!r} not in allowlist",
                                  {"url": url, "host": host}))
    return out


GATES = [
    ("json_schema", gate_1_schema),
    ("macro_consistency", gate_2_macros),
    ("allergen_taxonomy", gate_3_allergens),
    ("condition_vocab", gate_4_conditions),
    ("allergen_completeness", gate_5_allergen_completeness),
    ("duplicate_detection", gate_6_duplicates),
    ("outlier_kcal", gate_7_outliers),
    ("image_url", gate_8_image_urls),
]


# --- Fix-application ---
def apply_fixes(records: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Mutate records in place + return (records, fix_counts)."""
    counts: Counter[str] = Counter()
    for rec in records:
        # 8: NULL placeholder image URLs
        url = get_field(rec, "execution", "firebaseImageUrl")
        if url == PLACEHOLDER_IMAGE_URL:
            rec["execution"]["firebaseImageUrl"] = None
            counts["image_placeholder_nulled"] += 1

        # 3: normalise allergens via synonyms + drop unknowns
        allergens = get_field(rec, "matchingCriteria", "allergens", default=[]) or []
        clean = []
        for a in allergens:
            norm = ALLERGEN_SYNONYMS.get(a, a)
            if norm in ALLERGEN_ENUM:
                clean.append(norm)
            else:
                counts["allergen_unknown_dropped"] += 1
        rec.setdefault("matchingCriteria", {})["allergens"] = sorted(set(clean))

        # 4: collapse condition synonyms; strip allergen leaks
        for fld in ("recommendedForConditions", "contraindicatedConditions"):
            arr = get_field(rec, "matchingCriteria", fld, default=[]) or []
            cleaned: list[str] = []
            for c in arr:
                if c in ALLERGEN_ENUM or c in ALLERGEN_SYNONYMS:
                    counts["allergen_leak_removed_from_conditions"] += 1
                    continue
                canon = CONDITION_SYNONYMS.get(c, c)
                if canon in CANONICAL_CONDITIONS:
                    if canon != c:
                        counts["condition_synonym_collapsed"] += 1
                    cleaned.append(canon)
                else:
                    counts["condition_unknown_dropped"] += 1
            rec["matchingCriteria"][fld] = sorted(set(cleaned))

        # 5: backfill missing allergens from ingredient lexicon
        ings = get_field(rec, "execution", "ingredients", default=[]) or []
        expected = _collect_expected_allergens(ings)
        declared = set(rec["matchingCriteria"].get("allergens", []))
        missing = expected - declared
        if missing:
            rec["matchingCriteria"]["allergens"] = sorted(declared | missing)
            counts["allergen_backfilled"] += len(missing)

        # 5b: purine flag (gout_risk) — non-allergen
        if any(t in PURINE_HEAVY_INGREDIENTS for ing in ings for t in normalise(ing).split()):
            existing = set(rec["matchingCriteria"].get("contraindicatedConditions", []))
            if "gout" not in existing:
                existing.add("gout")
                rec["matchingCriteria"]["contraindicatedConditions"] = sorted(existing)
                counts["gout_contraindication_added"] += 1

        # ADR-0008: tag existing LatAm-origin catalog with regions=['latam']
        existing_regions = rec["matchingCriteria"].get("regions") or []
        if not existing_regions:
            rec["matchingCriteria"]["regions"] = ["latam"]
            rec.setdefault("_audit", {})["regions_inferred"] = (
                "tagged 'latam' from seed catalog provenance; needs human review for cross-region tagging"
            )
            counts["regions_inferred_latam"] += 1

        # Source-batch provenance
        rec.setdefault("execution", {}).setdefault("source_catalog", "nova_seed_v1")

    return records, dict(counts)


# --- Reporting ---
def summarise(results: list[GateResult]) -> dict[str, dict[str, int]]:
    summary: dict[str, dict[str, int]] = {}
    for name, _ in GATES:
        summary[name] = {"info": 0, "warn": 0, "fail": 0}
    for r in results:
        summary.setdefault(r.name, {"info": 0, "warn": 0, "fail": 0})[r.severity] += 1
    return summary


def audit(records: list[dict[str, Any]]) -> list[GateResult]:
    out: list[GateResult] = []
    for _name, fn in GATES:
        out.extend(fn(records))
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="NOVA catalog audit pipeline (8 gates)")
    parser.add_argument("catalog", type=Path, help="Path to catalog JSON")
    parser.add_argument("--apply-fixes", action="store_true",
                        help="Apply auto-fixes (synonym collapse, image NULLing, region backfill)")
    parser.add_argument("--output", type=Path, default=None,
                        help="Output cleaned catalog (only with --apply-fixes)")
    parser.add_argument("--report", type=Path, default=None,
                        help="Output report JSON path (default reports/catalog_audit_<ts>.json)")
    args = parser.parse_args(argv)

    catalog_path: Path = args.catalog
    if not catalog_path.exists():
        print(f"catalog not found: {catalog_path}", file=sys.stderr)
        return 2

    records = json.loads(catalog_path.read_text(encoding="utf-8"))
    if not isinstance(records, list):
        print("catalog must be a JSON array", file=sys.stderr)
        return 2

    started_at = datetime.now(timezone.utc).isoformat()
    sha = file_sha256(catalog_path)

    fix_counts: dict[str, int] = {}
    if args.apply_fixes:
        records, fix_counts = apply_fixes(records)

    results = audit(records)
    finished_at = datetime.now(timezone.utc).isoformat()

    passed = not any(r.severity == "fail" for r in results)
    report = AuditReport(
        catalog_path=str(catalog_path),
        catalog_sha256=sha,
        started_at=started_at,
        finished_at=finished_at,
        total_records=len(records),
        gates_summary=summarise(results),
        results=results,
        passed=passed,
    )

    # Write report
    if args.report is None:
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        report_path = Path("reports") / f"catalog_audit_{ts}.json"
    else:
        report_path = args.report
    report_path.parent.mkdir(parents=True, exist_ok=True)

    payload: dict[str, Any] = asdict(report)
    payload["fix_counts"] = fix_counts
    payload["constants"] = {
        "MACRO_TOLERANCE": MACRO_TOLERANCE,
        "allergen_enum_size": len(ALLERGEN_ENUM),
        "canonical_conditions_size": len(CANONICAL_CONDITIONS),
        "meal_times": sorted(MEAL_TIMES),
        "regions": sorted(REGIONS),
    }
    report_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"report → {report_path}")

    # Write cleaned catalog
    if args.apply_fixes and args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(records, indent=2, ensure_ascii=False),
                               encoding="utf-8")
        print(f"cleaned catalog → {args.output}")

    fail_count = sum(1 for r in results if r.severity == "fail")
    warn_count = sum(1 for r in results if r.severity == "warn")
    info_count = sum(1 for r in results if r.severity == "info")
    print(f"records={len(records)} fail={fail_count} warn={warn_count} info={info_count}")
    if fix_counts:
        print(f"fixes applied: {fix_counts}")

    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
