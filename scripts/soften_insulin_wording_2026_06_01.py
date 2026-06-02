"""Soften regulator-sensitive "insulina" wording in catalog descriptions.

QA review 2026-06-01 flagged 25 diabetes_t1 snack descriptions using the
literal word "insulina" (clinically correct context — talking about endogenous
glycemic response — but regulator-sensitive surface wording).

This script replaces:
  "ajuste fino de insulina"  →  "ajuste fino de respuesta glicémica"
  "manejo de insulina"       →  "manejo glicémico"
  "insulina endógena"        →  "respuesta glicémica endógena"

Idempotent. Audit trail in audit.patches[].
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

CATALOG = Path(__file__).resolve().parent.parent / "data" / "meals" / "nova_meals_catalog.cleaned.json"

# Order: longer phrases first to avoid double-replacement.
SUBS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"ajuste fino de insulin[ao]", re.IGNORECASE),
     "ajuste fino de respuesta glicémica"),
    (re.compile(r"manejo de insulin[ao]", re.IGNORECASE),
     "manejo glicémico"),
    (re.compile(r"insulin[ao] endógen[ao]", re.IGNORECASE),
     "respuesta glicémica endógena"),
    (re.compile(r"requerimientos? de insulin[ao]", re.IGNORECASE),
     "requerimientos glicémicos"),
    (re.compile(r"\binsulin[ao]\b", re.IGNORECASE),
     "respuesta glicémica"),
)


def _add_audit(recipe: dict[str, Any], patch: dict[str, Any]) -> None:
    audit = recipe.setdefault("audit", {})
    patches = audit.setdefault("patches", [])
    key = (patch.get("date"), patch.get("patch"))
    if any((p.get("date"), p.get("patch")) == key for p in patches):
        return
    patches.append(patch)


def main() -> int:
    data = json.loads(CATALOG.read_text())
    softened = 0

    for r in data:
        original_desc = r.get("description", "")
        original_name = r.get("name", "")
        new_desc = original_desc
        new_name = original_name

        for pat, repl in SUBS:
            new_desc = pat.sub(repl, new_desc)
            new_name = pat.sub(repl, new_name)

        if new_desc != original_desc or new_name != original_name:
            if new_desc != original_desc:
                r["description"] = new_desc
            if new_name != original_name:
                r["name"] = new_name
            softened += 1
            _add_audit(r, {
                "date": "2026-06-01",
                "patch": "legal_soften_insulin_wording",
                "reason": "regulator-sensitive surface wording",
            })

    CATALOG.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    print(f"softened: {softened}")

    # Verify
    remaining = sum(
        1 for r in data
        if re.search(r"\binsulin[ao]?s?\b", r.get("description", "") + " " + r.get("name", ""), re.I)
    )
    print(f"remaining insulin hits: {remaining}")
    return 0 if remaining == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
