"""Legal scope cleanup — catálogo nutrition-only.

Scope decision (2026-06-01): NOVA es planificador nutricional. NO recomienda
pastillas, vitaminas en suplemento, medicamentos. NO hace claims clínicos.

Acciones idempotentes sobre `data/meals/nova_meals_catalog.cleaned.json`:

  1. REMOVE recipes that include supplement ingredients (whey, casein,
     creatine, BCAA, pre-workout, mass-gainer powders).
     Rationale: these are commercial supplements; recommending them as
     ingredients = recommending supplements = out of scope.

  2. SOFTEN description language to remove medical-adjacent claims:
       "detox" → drop
       "antiinflamatorio/antiinflamatoria" → drop
       "cardioprotector/cardioprotectora" → drop
       "alta dosis natural de vitamina C" → "rico en vitamina C natural"
       "apoya/apoyo X (control glucémico, etc.)" → "aporta X"
       "mejora X (absorción/control)" → "favorece X"

  3. EXISTING soft-tags kept (informational only):
       "antioxidante" (factual nutritional description, no claim)
       "rico en vitamina C/D/etc" (food-source description, no supplement claim)
       "apto para hipertensión/diabetes" (informational, neutral)

  4. Track removed/modified counts + persistent audit entries on touched recipes.

Idempotent. Backup created at sibling .pre_legal_cleanup.bak.
"""
from __future__ import annotations

import json
import re
import shutil
import sys
from pathlib import Path
from typing import Any

CATALOG = Path(__file__).resolve().parent.parent / "data" / "meals" / "nova_meals_catalog.cleaned.json"
BACKUP = CATALOG.with_suffix(CATALOG.suffix + ".pre_legal_cleanup.bak")

# Supplement ingredient detector (case-insensitive, word-boundary).
_SUPPLEMENT_PATTERNS = (
    re.compile(r"\bwhey\b", re.IGNORECASE),
    re.compile(r"\bcase[ií]na\b", re.IGNORECASE),
    re.compile(r"\bcasein\b", re.IGNORECASE),
    re.compile(r"\bcreatina\b", re.IGNORECASE),
    re.compile(r"\bcreatine\b", re.IGNORECASE),
    re.compile(r"\bbcaa\b", re.IGNORECASE),
    re.compile(r"\bpre-?workout\b", re.IGNORECASE),
    re.compile(r"\bmass\s*gainer\b", re.IGNORECASE),
    re.compile(r"\bprote[íi]na en polvo\b", re.IGNORECASE),
    re.compile(r"\bprotein powder\b", re.IGNORECASE),
    re.compile(r"\bbeta-?alanina\b", re.IGNORECASE),
    re.compile(r"\bglutamina (?:en polvo|suplemento)\b", re.IGNORECASE),
    re.compile(r"\bcol[áa]geno (?:hidrolizado|en polvo|peptidos)\b", re.IGNORECASE),
    re.compile(r"\bcollagen (?:powder|peptides)\b", re.IGNORECASE),
    re.compile(r"\bmaltodextrina\b", re.IGNORECASE),
)


def _recipe_uses_supplements(recipe: dict[str, Any]) -> str | None:
    """Return matched supplement token if any, else None."""
    blobs: list[str] = [recipe.get("name", ""), recipe.get("description", "")]
    ex = recipe.get("execution") or {}
    blobs.extend(ex.get("ingredients") or [])
    blobs.extend(ex.get("instructions") or [])
    full = " || ".join(blobs)
    for pat in _SUPPLEMENT_PATTERNS:
        m = pat.search(full)
        if m:
            return m.group(0).lower()
    return None


# Description softening rules (order matters — more-specific first).
_CLAIM_SUBS: tuple[tuple[re.Pattern[str], str], ...] = (
    # "alta dosis natural de vitamina X" → "rico en vitamina X natural"
    (re.compile(r"\balta dosis natural de (vitamina [a-zA-Z]\d?)\b", re.IGNORECASE),
     r"rico en \1 natural"),
    # "antiinflamatorio/a/s" — drop adjective + dangling "por"/"con"
    (re.compile(r",?\s*antiinflamatori[oa]s?\b(?:\s+(?:por|con|gracias a)\s+\w+)?", re.IGNORECASE), ""),
    # "cardioprotector/a"
    (re.compile(r",?\s*cardioprotector[a]?s?\b", re.IGNORECASE), ""),
    # "detox" standalone
    (re.compile(r"\bdetox\b", re.IGNORECASE), "ligero"),
    # "apoya/apoyo X" → "aporta X"
    (re.compile(r"\bapoya (el|la|los|las) (control glucémico|control de presión|sistema inmune|metabolismo|recuperación|salud)\b", re.IGNORECASE),
     r"aporta \1 \2"),
    # "mejora X (absorción/control)" → "favorece X"
    (re.compile(r"\bmejora (el|la|los|las) (absorci[óo]n|control|funci[óo]n)\b", re.IGNORECASE),
     r"favorece \1 \2"),
    # "previene X" — should not exist but defensive
    (re.compile(r"\bpreviene\b", re.IGNORECASE), "asociado con"),
    # "reduce el X" softer
    (re.compile(r"\breduce (el|la|los|las) (colesterol|presi[óo]n|glucemia|inflamaci[óo]n|riesgo)\b", re.IGNORECASE),
     r"asociado con \1 \2 moderado"),
    # Double-spaces / leading commas left by deletions
    (re.compile(r"\s{2,}"), " "),
    (re.compile(r"\s+\.\s*$"), "."),
    (re.compile(r"\s+\.\s+"), ". "),
    (re.compile(r"^\s*,\s*"), ""),
    (re.compile(r"\.\s*\."), "."),
)


def _soften_description(text: str) -> tuple[str, list[str]]:
    """Apply claim-softening subs. Returns (new_text, applied_rule_names)."""
    applied: list[str] = []
    out = text
    for pat, repl in _CLAIM_SUBS:
        new = pat.sub(repl, out)
        if new != out:
            applied.append(pat.pattern[:50])
            out = new
    out = out.strip()
    if out and not out.endswith((".", "!", "?")):
        out += "."
    return out, applied


def _add_audit(recipe: dict[str, Any], entry: dict[str, Any]) -> None:
    audit = recipe.setdefault("audit", {})
    patches = audit.setdefault("patches", [])
    key = (entry.get("date"), entry.get("patch"))
    if any((p.get("date"), p.get("patch")) == key for p in patches):
        return
    patches.append(entry)


def main() -> int:
    if not CATALOG.exists():
        print(f"missing {CATALOG}", file=sys.stderr)
        return 2
    if not BACKUP.exists():
        shutil.copy2(CATALOG, BACKUP)
        print(f"backup: {BACKUP}")

    data = json.loads(CATALOG.read_text())
    if not isinstance(data, list):
        print("not a JSON array", file=sys.stderr)
        return 2

    kept: list[dict[str, Any]] = []
    removed_count = 0
    removed_breakdown: dict[str, int] = {}
    softened_count = 0
    softened_rule_counts: dict[str, int] = {}

    for r in data:
        # Step 1: remove if supplement detected
        match = _recipe_uses_supplements(r)
        if match:
            removed_count += 1
            removed_breakdown[match] = removed_breakdown.get(match, 0) + 1
            continue
        # Step 2: soften description claims
        desc = r.get("description") or ""
        if desc:
            new_desc, applied = _soften_description(desc)
            if applied:
                r["description"] = new_desc
                softened_count += 1
                for rule in applied:
                    softened_rule_counts[rule] = softened_rule_counts.get(rule, 0) + 1
                _add_audit(r, {
                    "date": "2026-06-01",
                    "patch": "legal_scope_soften_claims",
                    "rules_applied": applied,
                })
        kept.append(r)

    CATALOG.write_text(json.dumps(kept, ensure_ascii=False, indent=2) + "\n")

    print(f"\nremoved (supplement ingredients): {removed_count}")
    for k, n in sorted(removed_breakdown.items(), key=lambda x: -x[1]):
        print(f"  {k:24s}: {n}")
    print(f"\nsoftened (claim language):       {softened_count}")
    for k, n in sorted(softened_rule_counts.items(), key=lambda x: -x[1])[:10]:
        print(f"  {k[:48]:50s}: {n}")
    print(f"\nfinal catalog: {len(kept)} recipes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
