"""Grocery domain — entities, VO, categorisation rules."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID


class GroceryCategory(StrEnum):
    FRUITS_VEGETABLES = "fruits_vegetables"
    PROTEINS = "proteins"
    DAIRY = "dairy"
    PANTRY = "pantry"
    OTHER = "other"


@dataclass(slots=True)
class GroceryItem:
    id: UUID
    list_id: UUID
    category: GroceryCategory
    name: str
    amount: str | None = None
    purchased: bool = False


@dataclass(slots=True)
class GroceryList:
    id: UUID
    plan_id: UUID
    generated_at: datetime
    items: list[GroceryItem]


# Deterministic keyword → category mapping. Reviewed quarterly with nutrition
# team. Kept narrow (substring match, lowercased EN name). Anything unmatched
# falls back to PANTRY (safest default for ambient-stable items) or OTHER.
_CATEGORY_KEYWORDS: dict[GroceryCategory, tuple[str, ...]] = {
    GroceryCategory.FRUITS_VEGETABLES: (
        "apple", "banana", "berry", "berries", "orange", "lemon", "lime",
        "grape", "mango", "pineapple", "pear", "peach", "plum", "watermelon",
        "melon", "kiwi", "papaya", "avocado", "tomato", "potato", "onion",
        "garlic", "carrot", "broccoli", "spinach", "kale", "lettuce", "salad",
        "pepper", "cucumber", "zucchini", "squash", "pumpkin", "celery",
        "cabbage", "cauliflower", "asparagus", "mushroom", "corn", "bean",
        "lentil", "pea", "fruit", "vegetable", "herb", "parsley", "cilantro",
        "basil", "mint", "ginger", "manzana", "platano", "naranja", "tomate",
        "papa", "cebolla",
    ),
    GroceryCategory.PROTEINS: (
        "chicken", "beef", "pork", "turkey", "lamb", "fish", "salmon", "tuna",
        "shrimp", "egg", "tofu", "tempeh", "seitan", "meat", "steak", "ham",
        "bacon", "sausage", "pollo", "carne", "pescado", "huevo", "atun",
    ),
    GroceryCategory.DAIRY: (
        "milk", "yogurt", "cheese", "butter", "cream", "kefir", "leche",
        "queso", "yogur", "mantequilla",
    ),
    GroceryCategory.PANTRY: (
        "rice", "pasta", "noodle", "bread", "flour", "oat", "cereal", "quinoa",
        "couscous", "barley", "oil", "vinegar", "sugar", "salt", "spice",
        "sauce", "broth", "stock", "honey", "syrup", "jam", "peanut butter",
        "cocoa", "chocolate", "coffee", "tea", "canned", "arroz", "pan",
        "harina", "aceite", "azucar",
    ),
}


def categorise(name_en: str) -> GroceryCategory:
    n = name_en.lower().strip()
    for cat, keys in _CATEGORY_KEYWORDS.items():
        if any(k in n for k in keys):
            return cat
    return GroceryCategory.OTHER
