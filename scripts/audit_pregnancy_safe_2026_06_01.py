"""Retroactive pregnancy_safe audit (2026-06-01).

Scans every recipe with pregnancy_safe=true in the master catalog. Flips to
false if its ingredient list contains any explicit pregnancy-unsafe token
(raw fish, soft cheese, Hg-high fish, organ meat, alcohol, raw eggs). The
audit token list intentionally excludes ambiguous cases (feta, "wine" used
as cooking reduction) to avoid false positives — those are logged as
warnings only.

Match rules: case-insensitive, word-boundary, EN+ES tokens.

Outputs:
- Mutates data/meals/nova_meals_catalog.cleaned.json in place (overwrite).
- Backup written to data/meals/nova_meals_catalog.cleaned.json.pre_round2_2026_06_01.bak
  by the caller BEFORE this script runs (we only verify the .bak exists).
- Adds audit.pregnancy_safe_audit_2026_06_01 = {"flipped": true, "reason": "<token>"}
  to flipped recipes.
- Console + log report: total scanned, flipped, top reasons + sample IDs.
- scripts/audit_pregnancy_safe_2026_06_01.log

Run: uv run python scripts/audit_pregnancy_safe_2026_06_01.py
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "data" / "meals" / "nova_meals_catalog.cleaned.json"
BACKUP_EXPECTED = ROOT / "data" / "meals" / "nova_meals_catalog.cleaned.json.pre_round2_2026_06_01.bak"
LOG = ROOT / "scripts" / "audit_pregnancy_safe_2026_06_01.log"

# Hard tokens: word-boundary, case-insensitive. Some patterns use regex
# fragments (e.g. [oó]) to cover ES diacritic variants.
PREGNANCY_UNSAFE_TOKENS = [
    # Raw fish / sushi
    "sushi", "sashimi", "tartar", "tartare", "crudo", "cruda",
    "ceviche", "carpaccio", "poke", "raw fish",
    "pescado crudo", r"salm[oó]n crudo", r"at[uú]n crudo",
    # Soft / unpasteurized cheese (excluding feta — too ambiguous, see WARN below)
    "brie", "camembert", "roquefort", "gorgonzola", "blue cheese", "queso azul",
    "queso fresco artesanal",
    # High-mercury fish
    "shark", r"tibur[oó]n", "swordfish", "pez espada", "king mackerel",
    "tilefish", "marlin", "bigeye tuna", r"at[uú]n rojo", "bluefin tuna",
    # Liver / organ
    "liver", r"h[ií]gado", r"pat[eé] de h[ií]gado", "foie gras",
    r"ri[ñn][oó]n", "kidney", "sweetbread", "mollejas",
    # Alcohol (strong only — "wine" alone excluded as cooking reduction)
    "whisky", "whiskey", "rum", "vodka", "tequila", "vino tinto",
    "licor", "brandy", "champagne", "champa[ñn]a",
    # Raw eggs
    "raw egg", "huevo crudo", "mayonesa casera", "homemade mayo", r"tiramis[uú]",
]

UNSAFE_REGEX = re.compile(
    r"(?<![\w])(?:" + "|".join(PREGNANCY_UNSAFE_TOKENS) + r")(?![\w])",
    re.IGNORECASE,
)

# Ambiguous tokens — log only, do NOT auto-flip.
AMBIGUOUS_TOKENS = ["feta", " wine ", "vino blanco"]


def first_unsafe(text: str) -> str | None:
    m = UNSAFE_REGEX.search(text)
    return m.group(0).lower() if m else None


def ambiguous_hits(text: str) -> list[str]:
    low = text.lower()
    return [t.strip() for t in AMBIGUOUS_TOKENS if t in low]


def main() -> None:
    if not BACKUP_EXPECTED.exists():
        print(f"WARN: expected backup not found at {BACKUP_EXPECTED}", file=sys.stderr)
        print("Proceeding anyway; ensure you have a backup before continuing.", file=sys.stderr)

    catalog = json.loads(CATALOG.read_text())
    assert isinstance(catalog, list)

    scanned = 0
    flipped = 0
    flipped_already_false = 0  # tracked separately for honesty
    reason_counts: Counter[str] = Counter()
    reason_samples: defaultdict[str, list[str]] = defaultdict(list)
    ambiguous_counts: Counter[str] = Counter()
    ambiguous_samples: defaultdict[str, list[str]] = defaultdict(list)

    for r in catalog:
        if not isinstance(r, dict):
            continue
        mc = r.get("matching_criteria")
        if not isinstance(mc, dict):
            continue
        if mc.get("pregnancy_safe") is not True:
            continue
        scanned += 1
        ex = r.get("execution") or {}
        ings = ex.get("ingredients") or []
        text = " ".join(str(x) for x in ings) + " " + (r.get("name") or "")
        token = first_unsafe(text)
        if token:
            mc["pregnancy_safe"] = False
            audit = r.setdefault("audit", {})
            audit["pregnancy_safe_audit_2026_06_01"] = {
                "flipped": True,
                "reason_token": token,
            }
            reason_counts[token] += 1
            if len(reason_samples[token]) < 5:
                reason_samples[token].append(r.get("id", "?"))
            flipped += 1
            continue
        # Ambiguous: record but don't flip.
        ambig = ambiguous_hits(text)
        for a in ambig:
            ambiguous_counts[a] += 1
            if len(ambiguous_samples[a]) < 5:
                ambiguous_samples[a].append(r.get("id", "?"))

    CATALOG.write_text(json.dumps(catalog, ensure_ascii=False))

    lines: list[str] = [
        "Pregnancy_safe retroactive audit (2026-06-01)",
        f"total_catalog={len(catalog)}",
        f"scanned_preg_safe_true_before={scanned}",
        f"flipped_to_false={flipped}",
        f"remaining_preg_safe_true_after={scanned - flipped}",
        "",
        "Top 10 flip reasons (token : count):",
    ]
    for tok, cnt in reason_counts.most_common(10):
        lines.append(f"  {tok!r}: {cnt}")
        sample_ids = reason_samples[tok]
        lines.append(f"    samples: {sample_ids}")

    lines.append("")
    lines.append("Ambiguous hits (NOT flipped, logged only):")
    for tok, cnt in ambiguous_counts.most_common(20):
        lines.append(f"  {tok!r}: {cnt} samples={ambiguous_samples[tok]}")

    LOG.write_text("\n".join(lines))
    print(f"audit: scanned={scanned} flipped={flipped}")
    print(f"top_reasons: {dict(reason_counts.most_common(10))}")


if __name__ == "__main__":
    main()
