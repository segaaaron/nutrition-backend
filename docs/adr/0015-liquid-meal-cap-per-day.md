# ADR-0015 — Liquid meal cap per day (Layer 4 coherence)

**Status:** Accepted
**Date:** 2026-06-01

## Decision

Layer 4 coherence enforces a hard cap on the number of `meal_format = "liquid"` recipes per daily plan:

| Goal | Max liquid meals/day |
|------|----------------------|
| `weight_loss` | 1 |
| `health`, `maintain`, `muscle_gain`, `weight_gain` | 2 |

## Why

Liquid meals (jugos, smoothies, batidos) have a satiety problem: caloric drinks empty the stomach faster than equivalent-calorie solid food. Over-recommending them to weight_loss users → poor adherence → churn.

Research summary:
- Solid kcal → ~60-90 min satiety
- Liquid kcal → ~20-40 min satiety
- Liquid-heavy diets correlate with snacking spikes between meals

## Constraint implementation

```python
class LiquidCap(Constraint):
    name = "liquid_cap"
    def check(self, plan: DraftPlan) -> list[Violation]:
        max_allowed = 1 if plan.targets.goal == "weight_loss" else 2
        n_liquid = sum(1 for slot in plan.meals if slot.recipe.meal_format == "liquid")
        if n_liquid > max_allowed:
            return [Violation(
                constraint="liquid_cap",
                magnitude=Decimal(n_liquid - max_allowed),
                slot_index=None,
            )]
        return []
```

Greedy solver: when violated, swap surplus liquid meal for next-best solid alternative in same slot.

## Catalog implication

Liquid recipes carry `meal_format = "liquid"`. Today's catalog (33,758 recipes) has ~250 liquid + ~280 semi_solid. Plenty of headroom for cap to not block plans.

## Consequences

- Mobile shows daily plan visually distinguishing liquid vs solid slots.
- Telemetry: track liquid recipe acceptance/swap rate post-launch.
- If real users prove liquid-heavy preference works for them, ADR can relax cap to user-configurable post-MVP.

## Alternatives considered

1. No cap — rejected: satiety research consistent.
2. Cap = 0 — rejected: smoothies + jugos are core user-requested content (viral marketing).
3. User-configurable cap — deferred: introduces preference complexity without v1 data.

## References

- `app/plan/domain/context.py::DraftPlan`
- `app/plan/domain/ports.py::Constraint`
- Master plan `docs/algorithms/MASTER_PLAN_ALGORITHM.md` §H1.5
