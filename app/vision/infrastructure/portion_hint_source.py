"""DB-backed portion hint source for two-pass vision pipeline.

Queries recipe_components to get typical serving weights and energy density
for identified ingredient names. Used by RecognisePlate._load_hints().
"""
from __future__ import annotations

import unicodedata
from collections.abc import Mapping, Sequence

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.vision.domain.value_objects import PortionHint

log = get_logger("vision.portion_hints")

# Min word length to use as a search keyword (avoids "al", "de", "la" etc.)
_MIN_KEYWORD_LEN = 4

# Stop words to strip before keyword extraction (prepositions + cooking methods)
_STOP = frozenset({
    # Spanish prepositions / articles
    "al", "a", "la", "con", "de", "en", "el", "los", "las", "del", "un", "una",
    "para", "por", "sin", "sobre", "entre",
    # Cooking methods / adjectives that don't identify the ingredient
    "cocido", "cocinada", "cocinado", "frito", "frita", "asado", "asada",
    "hervido", "hervida", "horneado", "horneada", "crudo", "cruda",
    "vapor", "plancha", "parrilla", "salteado", "salteada", "revuelto", "revuelta",
    "fresco", "fresca", "natural", "entero", "entera", "picado", "picada",
    "rallado", "rallada", "partido", "partida", "molido", "molida",
    "mixta", "mixto", "verde", "blanca", "blanco", "rojo", "roja",
    "integral", "light", "bajo",
})


def _extract_keyword(name: str) -> str:
    """Normalize name → first meaningful word for catalog ILIKE search.

    Uses the first word that is not a stop word and has at least 4 chars.
    Falls back to the raw first word if all words are filtered out.

    Examples:
      "pollo al horno"       → "pollo"
      "arroz con pollo"      → "arroz"
      "ensalada mixta"       → "ensalada"
      "huevo revuelto"       → "huevo"
      "fideos salteados"     → "fideos"
    """
    # lowercase + strip accents
    s = unicodedata.normalize("NFD", name.strip().lower())
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    # remove punctuation
    s = "".join(c if c.isalpha() or c == " " else " " for c in s)

    parts = s.split()
    for word in parts:
        if word not in _STOP and len(word) >= _MIN_KEYWORD_LEN:
            return word
    # fallback: first word regardless of length or stop status
    return parts[0] if parts else ""


async def _query_hint(session: AsyncSession, name: str) -> tuple[str, PortionHint | None]:
    """Single ingredient lookup. Returns (original_name, hint_or_none)."""
    keyword = _extract_keyword(name)
    if not keyword:
        return name, None

    row = (
        await session.execute(
            text(
                """
                SELECT
                    AVG(rc.amount_g)::float                                  AS avg_g,
                    AVG(
                        CASE
                            WHEN f.portion_g > 0 AND f.kcal IS NOT NULL
                            THEN f.kcal * 100.0 / f.portion_g
                            ELSE NULL
                        END
                    )::float                                                 AS kcal_per_100g
                FROM recipe_components rc
                LEFT JOIN foods f ON f.id = rc.food_id
                WHERE lower(rc.free_text_name) LIKE :pattern
                  AND rc.amount_g > 0
                  AND rc.amount_g < 1500
                """
            ),
            {"pattern": f"%{keyword}%"},
        )
    ).first()

    if row is None or row[0] is None:
        return name, None

    avg_g: float = row[0]
    kcal_per_100g: float | None = row[1]

    return name, PortionHint(
        name_norm=keyword,
        typical_serving_g=round(avg_g, 1),
        kcal_per_100g=round(kcal_per_100g, 1) if kcal_per_100g is not None else None,
    )


class SqlPortionHintSource:
    """Batch portion hint queries against recipe_components + foods tables."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def load_hints(self, names: Sequence[str]) -> Mapping[str, PortionHint]:
        if not names:
            return {}

        # SEQUENTIAL — MUST NOT gather. All queries share one AsyncSession
        # (single connection); firing them concurrently interleaves operations
        # on the same connection → SQLAlchemy IllegalStateChangeError (the exact
        # race documented at process_vision_job.py:163 and create_plan.py). A
        # shared connection serialises anyway, so gather buys no parallelism —
        # only the race. Item counts per plate are small (~2-8), so N awaits are
        # cheap. Each query is independently guarded so one failure never aborts
        # the rest; hints are best-effort (see RecognisePlate._load_hints).
        out: dict[str, PortionHint] = {}
        for name in names:
            try:
                orig_name, hint = await _query_hint(self._session, name)
            except Exception as exc:  # noqa: BLE001 — best-effort; one bad lookup must not sink the batch
                log.warning("vision.hints.query_error", name=name, error=str(exc))
                continue
            if hint is not None:
                out[orig_name] = hint

        log.info("vision.hints.loaded", n_requested=len(names), n_found=len(out))
        return out
