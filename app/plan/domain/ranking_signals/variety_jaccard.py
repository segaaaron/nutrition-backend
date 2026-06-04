"""H1.5 - Variety penalty via Jaccard similarity over recent history.

Definition
----------
Let ``C`` be the candidate recipe's *concept set* (tags ∪ ingredient
classes) and ``H`` the union of tags and ingredient classes used by the
user in the last 14 days. The variety score is::

    variety = 1 - jaccard(C, H) = 1 - |C ∩ H| / |C ∪ H|

Edge cases
----------
* ``C ∪ H = ∅``  → return ``Decimal("0.5")`` (no information, neutral).
* ``C = ∅`` and ``H ≠ ∅`` → ambiguous (totally novel by absence of
  features). We return ``Decimal("0.5")`` for safety.
* Candidate already eaten in the last 7 days → hard cap
  ``Decimal("0")`` regardless of tag overlap. This protects against
  near-term repetition even when the recipe's concept set is small.

MVP scope
---------
``RecipeView`` today exposes ``tags`` only; ``ingredient_classes`` is
planned for a separate migration. Until then the candidate side of the
Jaccard uses ``frozenset(recipe.tags)`` only, while the history side
still unions tags ∪ ingredient_classes from ``RecentRecipesReader``.
Documented as a known asymmetry; it does not break the [0,1] bound.

All math is ``Decimal``. Result is quantized to 4 decimal places using
``ROUND_HALF_EVEN``.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Decimal

from app.plan.domain.context import PlanGenContext, RecipeView
from app.plan.domain.recent_recipes import RecentRecipesReader

_NEUTRAL: Decimal = Decimal("0.5")
_HARD_CAP: Decimal = Decimal("0")
_ONE: Decimal = Decimal("1")
_QUANT: Decimal = Decimal("0.0001")


@dataclass(slots=True)
class JaccardVarietyPenalty:
    """RankingSignal that rewards candidates dissimilar to recent history.

    The dataclass is intentionally non-frozen because ``key`` is a
    Protocol-required attribute; the instance itself is otherwise
    stateless and safe to share across requests.
    """

    reader: RecentRecipesReader
    key: str = "variety_jaccard"

    async def score(self, recipe: RecipeView, ctx: PlanGenContext) -> Decimal:
        # 1) Hard 7-day repetition cap — short-circuits everything else.
        recent_ids = await self.reader.recipe_ids_used_7d(ctx.user_id)
        if recipe.id in recent_ids:
            return _HARD_CAP

        # 2) Build sets.
        recent_tags = await self.reader.tags_used_14d(ctx.user_id)
        recent_classes = await self.reader.ingredient_classes_used_14d(ctx.user_id)
        recent_set: frozenset[str] = recent_tags | recent_classes
        candidate_set: frozenset[str] = frozenset(recipe.tags)

        # 3) Empty cases.
        union = candidate_set | recent_set
        if len(union) == 0:
            return _NEUTRAL
        if len(candidate_set) == 0:
            # Recent is non-empty but candidate has no concepts: ambiguous.
            return _NEUTRAL

        # 4) Jaccard similarity → variety = 1 - jaccard.
        intersection_size = len(candidate_set & recent_set)
        union_size = len(union)
        jaccard = Decimal(intersection_size) / Decimal(union_size)
        variety = _ONE - jaccard

        # 5) Quantize for deterministic serialisation.
        return variety.quantize(_QUANT, rounding=ROUND_HALF_EVEN)
