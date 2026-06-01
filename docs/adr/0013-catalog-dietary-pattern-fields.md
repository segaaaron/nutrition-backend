# ADR-0013 — Catalog v2 schema fields: dietary_pattern + cuisine_region + meal_format

**Status:** Accepted (shipped)
**Date:** 2026-06-01

## Decision

Three additive fields on `matching_criteria` per recipe:

| Field | Type | Default existing | Required new |
|-------|------|------------------|--------------|
| `dietary_pattern` | enum `omnivore \| pescatarian \| vegetarian \| vegan` | inferred `omnivore` | yes |
| `cuisine_region` | list[enum] `latam \| mediterranean \| asian \| middle_eastern \| north_american \| nordic \| african \| fusion` | inferred from ingredients | yes |
| `meal_format` | enum `solid \| semi_solid \| liquid` | `solid` | yes |

## Why

Master plan H1.5 (variety) + H2 (clinical filtering) require these to ship safe-quality recipe ranking.

- `dietary_pattern`: without it, vegan users silently receive meat recipes. Mandatory mobile form field per ADR-0014.
- `cuisine_region`: drives variety signal + cultural fit; future micro-region split for LatAm sub-cuisines.
- `meal_format`: separates "when you eat" (`meal_time`) from "what form it has". Liquids fit `breakfast`/`snack` slots without enum proliferation. Enables per-day liquid caps (ADR-0015).

## Backward compatibility

`meal_times_4` enum stays unchanged. Existing 2,000 recipes inferred `dietary_pattern` via ingredient regex (`scripts/migrate_catalog_schema_v2.py`).

## Consequences

- Catalog schema v2 universal snake_case.
- Algorithm Layer 1 can filter by dietary_pattern when user supplies it.
- Variety signal can group by cuisine_region.
- Liquid cap constraint (Layer 4) reads `meal_format = "liquid"`.

## Migration

DB-side: covered by future migration 0011 (deferred until catalog seed runs in DB; until then file-only).

## References

- `app/shared/domain/vocabularies.py`
- `data/meals/nova_meals_catalog.cleaned.json` (33,758 recipes post-round 3)
- `scripts/migrate_catalog_schema_v2.py`
- ADR-0001 closed vocabularies
