"""0033 — exclude species-ambiguous fish from landlocked markets.

Revision: 0033_ambiguous_fish_landlocked
Author:   nova-backend-architect
Date:     2026-07-17

CLAUDE.md §REGLA PAÍSES SIN MAR bans sea fish in Bolivia and Paraguay and
allows freshwater fish. The catalog honours that for anything NAMED after a
sea species (salmón, atún, bacalao…) — those already carry the exclusion —
and it has 33 recipes that name a freshwater species outright ("Pescado de
río…", trucha, tilapia).

What leaks is the middle: 57 recipes named only "Filete de pescado blanco"
or "Pescado blanco", which never say which fish. They are not identifiable
as marine, so no filter stops them — a BO user's 2026-07-17 plan served
"Filete de pescado blanco al horno con puré de papa". And the repo's own
ingredient map resolves that ingredient as:

    "Filete de pescado blanco (tilapia, corvina o similar)"
        -> "White fish fillet (tilapia, sea bass or similar)"

Corvina is a SEA fish. So the ingredient is genuinely ambiguous by
definition, not merely under-described, and in a landlocked market it cannot
be assumed freshwater.

Owner decision 2026-07-17: exclude them in BO/PY rather than re-specify the
species, since those markets keep the 33 explicit freshwater recipes (23
lunch + 10 dinner — comfortably more than a 7-day plan's 7 per slot).

Scope note: BO/PY only, matching `_LANDLOCKED_COUNTRIES` in
layer1_eligibility.py ("scoped to active markets"), not the full 46-country
list. Idempotent: recipes already excluding both codes are skipped, and the
array is rebuilt DISTINCT so re-running cannot duplicate an entry.
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import text

revision = "0033_ambiguous_fish_landlocked"
down_revision = "0032_unblock_landlocked_smoothies"
branch_labels = None
depends_on = None

# Named after a freshwater species → already safe for landlocked markets.
_FRESHWATER = (
    r"(de río|de rio|trucha|surubi|surubí|pacu|pacú|paiche|tilapia|sabalo|"
    r"sábalo|dorado|boga|tararira|bagre|carpa|pejerrey)"
)
# Named after a sea species → already excluded by the sea-fish tagging.
_SEA = r"(salmon|salmón|atun|atún|bacalao|anchoa|sardina)"


def upgrade() -> None:
    conn = op.get_bind()
    res = conn.execute(
        text(
            """
            UPDATE recipes r SET excluded_countries = (
                SELECT array_agg(DISTINCT c ORDER BY c)
                  FROM unnest(r.excluded_countries || ARRAY['BO', 'PY']) AS c
            )
             WHERE lower(coalesce(r.name_translations->>'es', r.name_en)) ~ '\\m(pescado|fish)\\M'
               AND NOT lower(coalesce(r.name_translations->>'es', r.name_en)) ~ :freshwater
               AND NOT lower(coalesce(r.name_translations->>'es', r.name_en)) ~ :sea
               AND NOT (r.excluded_countries @> ARRAY['BO', 'PY'])
            """
        ),
        {"freshwater": _FRESHWATER, "sea": _SEA},
    )
    print(f"0033: excluded {res.rowcount} ambiguous-fish recipes from BO/PY")  # noqa: T201


def downgrade() -> None:
    # No-op, deliberately. 20 of the ambiguous-fish recipes ALREADY excluded
    # BO/PY before this migration ran (tagged from their ingredients rather
    # than their name), and the upgrade does not record which rows it touched.
    # A downgrade that strips BO/PY from everything matching the criteria
    # would therefore also strip those 20 — turning a rollback into a new
    # bug, and re-serving sea fish in a landlocked market. Restoring the
    # exclusion state means restoring from the 2026-07-17 pre-fix dump.
    pass
