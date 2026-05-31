# NOVA Catalog Ingest Pipeline — Design Spec

- Date: 2026-05-30
- Status: Design only (no implementation yet)
- Owner: nova-nutrition-backend-architect
- Sign-off gate for: any `scripts/seed_recipes.py` run against production DB.

## 1. Goal

Every batch of `nova_meals_catalog.json` (or any upstream catalog JSON) passes
through a deterministic audit pipeline before SQL touches the recipes /
recipe_components / recipe_allergens tables. The audit produces a structured
report and exits non-zero on the first failed gate, blocking ingest.

## 2. Architecture

```
upstream JSON   ──►   scripts/audit_catalog.py   ──►   reports/catalog_audit_<ts>.json
                            │
                            ▼
                     (all gates pass?)
                            │
                  yes ◄──── │ ────► no  →  exit 1, CI artifact, ingest blocked
                            ▼
              scripts/seed_recipes.py (refuses to run unless latest report is green)
                            ▼
                       Postgres
```

- Single Python entry point, no service. Runs in CI on PRs that touch
  `data/meals/*.json` and as a pre-step in the seed job.
- All side effects (file writes, DB writes) gated by an explicit
  `--apply` flag. Default is dry-run.

## 3. Eight data-quality gates

Order matters: each gate assumes the previous gates passed.

### Gate 1 — JSON Schema conformance
- Validate every record against `schemas/catalog_record.json` (Draft 2020-12).
- Required fields: `id, name, mealtime, ingredients[], proteinG, carbsG, fatG,
  kcal, allergens[], recommendedForConditions[], contraindicatedConditions[]`.
- Unknown top-level keys are warnings, not errors (forward compatibility).

### Gate 2 — Macro consistency
- For each record: `abs(kcal - (proteinG*4 + carbsG*4 + fatG*9)) / kcal <= 0.02`.
- Constant pulled from `app/shared/domain/macro_tolerance.py::MACRO_TOLERANCE`
  (single source of truth, see spec §6).

### Gate 3 — Allergen taxonomy (closed)
- `allergens ⊆ allergen_enum` where `allergen_enum` is sourced from
  `app/recipes/domain/allergens.py::AllergenEnum` (mirrors the Postgres ENUM).
- Unknown values fail the record. Sesame is included (ADR-0001).

### Gate 4 — Condition vocabulary
- `recommendedForConditions ⊆ canonical_conditions`
  AND `contraindicatedConditions ⊆ canonical_conditions`
  AND `(recommended ∪ contraindicated) ∩ allergen_enum == ∅`.
- `canonical_conditions` lives in `app/recipes/domain/conditions.py` (ADR-0001).

### Gate 5 — Allergen completeness (ingredient lexicon)
- Build a set of expected allergens from `ingredients[]` using the lexicon
  below. If `expected - declared != ∅`, fail the record.
- Lexicon excerpt (≥40 mappings; full table maintained in
  `app/recipes/domain/ingredient_allergen_lexicon.py`):

| Spanish ingredient keyword | Allergen tag |
|---|---|
| leche, lacteo, queso, yogur, yogurt, mantequilla, crema, requeson, ricotta, mozzarella, parmesano, cheddar, feta, suero | `dairy` |
| trigo, harina, pan, pasta, fideo, tallarin, espagueti, bagel, cuscus, bulgur, seitan, cebada, centeno, malta | `gluten` |
| almendra, nuez, pistacho, avellana, anacardo, marañon, castaña, brasil, macadamia, piñon, pecana | `tree_nuts` |
| mani, cacahuate, cacahuete | `peanuts` |
| camaron, langostino, langosta, cangrejo, mejillon, almeja, ostion, ostra, calamar, pulpo, vieira | `shellfish` |
| salmon, atun, anchoa, sardina, bacalao, merluza, trucha, tilapia, pescado, anchova | `fish` |
| huevo, clara, yema, mayonesa | `egg` |
| soja, soya, tofu, edamame, tempeh, miso, tamari, salsa de soja | `soy` |
| sesamo, ajonjoli, tahini, tahin, gomashio | `sesame` |

(Total ≥ 50 keyword → 9 allergen mappings.) Word boundaries are normalised
(unaccent, lowercase, NFKC) before matching to avoid false negatives on
"salmón" vs "salmon".

### Gate 6 — Duplicate detection
- Normalise names: `unaccent(lower(strip_punct(name)))`.
- Pairwise Levenshtein distance ≤ 2 between any two records → both flagged.
- Behaviour: warn for distance > 0; fail only for distance == 0 with
  identical `mealtime`. Distance 1–2 produces an entry in
  `report.duplicates_for_review` (human triage).

### Gate 7 — Outlier detection
- Per `mealtime` cluster: compute `mean(kcal)` and `stdev(kcal)`.
- `z = (kcal - mean) / stdev`; fail if `|z| > 4`.
- Justification: bounded at 4σ to catch obvious data-entry errors
  (e.g. 4500 kcal "snack") without rejecting legitimate calorie-dense dishes.

### Gate 8 — Image URL sanity
- If `firebaseImageUrl == 'https://storage.googleapis.com/tu-proyecto/placeholder.webp'`
  (the known placeholder), rewrite to `NULL` (warning, not error).
- Any non-`https://` URL → fail the record.
- Any URL whose host is not in the allowlist
  `{storage.googleapis.com, cdn.nova-nutrition.com}` → fail the record.

## 4. Language mapping (catalog en → DB es)

Authoritative bridge from English catalog values to Spanish DB enums.
Lives in `app/recipes/infrastructure/catalog_language_map.py`.

| Catalog (en) | DB (es) | Field |
|---|---|---|
| `breakfast` | `desayuno` | `meal_time` |
| `lunch` | `almuerzo` | `meal_time` |
| `dinner` | `cena` | `meal_time` |
| `snack` | `snack` | `meal_time` |
| `weight_loss` | `bajar` | objetivo |
| `weight_maintenance` | `mantener` | objetivo |
| `weight_gain` | `ganar_peso` | objetivo |
| `muscle_building` / `build_muscle` / `muscle_hypertrophy` | `ganar_musculo` | objetivo |
| `general_health` / `general_wellness` | `salud` | objetivo |
| `sedentary` | `sedentario` | nivel_actividad |
| `light` | `ligero` | nivel_actividad |
| `moderate` | `moderado` | nivel_actividad |
| `active` | `activo` | nivel_actividad |
| `athlete` / `very_active` | `atleta` | nivel_actividad |

Condition labels: a separate normalisation table collapses duplicates
(`peanut_allergy` → rejected via gate 3 because it is an allergen, not a
condition; `muscle_building` → `ganar_musculo`; `cardiovascular_health` /
`cardiovascular_disease_prevention` → `cardiovascular_health` canonical).

## 5. `scripts/audit_catalog.py` interface (design contract)

```python
# scripts/audit_catalog.py — design contract only, no implementation here.

from pathlib import Path
from typing import Literal, TypedDict

Severity = Literal["info", "warn", "fail"]

class GateResult(TypedDict):
    gate: int
    name: str
    severity: Severity
    record_id: str | None     # None for aggregate gates (6, 7)
    message: str
    context: dict             # gate-specific structured detail

class AuditReport(TypedDict):
    catalog_path: str
    catalog_sha256: str
    started_at: str           # ISO-8601 UTC
    finished_at: str
    total_records: int
    results: list[GateResult]
    passed: bool              # True iff zero results with severity=='fail'

def audit_catalog(
    catalog_path: Path,
    *,
    apply_url_normalisation: bool = False,  # writes a *.cleaned.json next to input
) -> AuditReport:
    """Run gates 1–8 in order. Pure function over filesystem (no DB)."""

def write_report(report: AuditReport, out_dir: Path) -> Path:
    """Serialise to reports/catalog_audit_<sha256>_<ts>.json. Returns path."""

def main(argv: list[str]) -> int:
    """CLI entry: argparse(--catalog PATH, --report-dir PATH, --apply).
       Exit 0 if report.passed else 1. Always writes the report.
    """
```

Out of scope for this design: ingest itself (`scripts/seed_recipes.py`), the
Postgres-side ENUM creation (handled by Alembic 0001), the UI surface for the
audit report (CI artifact only for MVP).

## 6. CI integration

- PR check: any change under `data/meals/**` triggers
  `python scripts/audit_catalog.py --catalog data/meals/nova_meals_catalog.json`.
- Required status check; PR blocked on failure.
- Report uploaded as a CI artifact for every run.

## 7. Open items

- Lexicon coverage will need expansion for Brazilian Portuguese ingredients
  before the `pt-BR` corpus lands.
- Condition canonicalisation table needs nutritionist review before first
  prod ingest.
- Outlier threshold (4σ) is a defensible default; revisit after the first 5k
  curated records to see if 3σ is feasible without false positives on dense
  cultural dishes (e.g. Peruvian lomo saltado).
