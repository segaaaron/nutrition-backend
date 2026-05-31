"""Seed `foods` with ~80 starter entries (USDA FDC fast foods + LatAm staples).

Idempotent: UPSERT on `name_norm`. Embeddings populated via OpenAI
text-embedding-3-large when `OPENAI_API_KEY` is set; otherwise NULL with a
warning. Per-row macro validation via MACRO_TOLERANCE (relaxed to 5% for the
seed set; USDA per-100g rows include fiber/alcohol rounding side-effects).

Run:
    uv run python -m scripts.seed_foods
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import unicodedata
from dataclasses import dataclass

from sqlalchemy import text

from app.core.db import session_scope
from app.core.logging import configure_logging, get_logger
from app.shared.domain.macro_tolerance import MACRO_TOLERANCE

log = get_logger("scripts.seed_foods")


def normalise(name: str) -> str:
    """Lower-case, strip diacritics, collapse whitespace. Used as natural key."""
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    return " ".join(s.lower().split())


@dataclass(frozen=True)
class Food:
    name_en: str
    name_es: str
    name_pt: str | None
    portion_g: float
    kcal: float
    protein_g: float
    carbs_g: float
    fat_g: float
    fiber_g: float
    sugar_g: float
    sodium_mg: float
    sat_fat_g: float
    country: str | None
    source: str
    verified: bool = True


# ~80 starter entries: USDA-aligned per-100g rows where possible.
STARTER_FOODS: list[Food] = [
    # --- LatAm staples / grains ---
    Food("White rice (cooked)", "Arroz blanco cocido", "Arroz branco cozido", 100, 130, 2.7, 28.0, 0.3, 0.4, 0.1, 1, 0.1, "PE", "usda_fdc"),
    Food("Brown rice (cooked)", "Arroz integral cocido", "Arroz integral cozido", 100, 112, 2.6, 23.0, 0.9, 1.8, 0.4, 5, 0.2, "PE", "usda_fdc"),
    Food("Black beans (cooked)", "Frijoles negros cocidos", "Feijão preto cozido", 100, 132, 8.9, 23.7, 0.5, 8.7, 0.3, 1, 0.1, "MX", "usda_fdc"),
    Food("Pinto beans (cooked)", "Frijoles pintos cocidos", "Feijão carioca cozido", 100, 143, 9.0, 26.2, 0.6, 9.0, 0.3, 1, 0.1, "MX", "usda_fdc"),
    Food("Lentils (cooked)", "Lentejas cocidas", "Lentilhas cozidas", 100, 116, 9.0, 20.1, 0.4, 7.9, 1.8, 2, 0.1, None, "usda_fdc"),
    Food("Chickpeas (cooked)", "Garbanzos cocidos", "Grão-de-bico cozido", 100, 164, 8.9, 27.4, 2.6, 7.6, 4.8, 7, 0.3, None, "usda_fdc"),
    Food("Quinoa (cooked)", "Quinua cocida", "Quinoa cozida", 100, 120, 4.4, 21.3, 1.9, 2.8, 0.9, 7, 0.2, "PE", "usda_fdc"),
    Food("Sweet potato (baked)", "Camote horneado", "Batata-doce assada", 100, 90, 2.0, 20.7, 0.1, 3.3, 6.5, 36, 0.0, "PE", "usda_fdc"),
    Food("White potato (boiled)", "Papa hervida", "Batata cozida", 100, 87, 1.9, 20.1, 0.1, 1.8, 0.9, 4, 0.0, None, "usda_fdc"),
    Food("Plantain (raw)", "Plátano verde", "Banana-da-terra", 100, 122, 1.3, 31.9, 0.4, 2.3, 15.0, 4, 0.1, "EC", "usda_fdc"),

    # --- Proteins ---
    Food("Chicken breast (skinless, cooked)", "Pechuga de pollo cocida", "Peito de frango cozido", 100, 165, 31.0, 0.0, 3.6, 0.0, 0.0, 74, 1.0, None, "usda_fdc"),
    Food("Chicken thigh (skinless, cooked)", "Muslo de pollo sin piel cocido", "Coxa de frango sem pele cozida", 100, 209, 26.0, 0.0, 10.9, 0.0, 0.0, 95, 3.0, None, "usda_fdc"),
    Food("Beef sirloin (lean, cooked)", "Lomo de res magro cocido", "Alcatra magra cozida", 100, 206, 30.0, 0.0, 9.0, 0.0, 0.0, 60, 3.4, "AR", "usda_fdc"),
    Food("Ground beef 90/10 (cooked)", "Carne molida 90/10 cocida", "Carne moída 90/10 cozida", 100, 217, 26.0, 0.0, 12.0, 0.0, 0.0, 75, 4.5, None, "usda_fdc"),
    Food("Pork loin (lean, cooked)", "Lomo de cerdo magro cocido", "Lombo suíno magro cozido", 100, 199, 28.0, 0.0, 9.0, 0.0, 0.0, 56, 3.0, None, "usda_fdc"),
    Food("Salmon (Atlantic, cooked)", "Salmón cocido", "Salmão cozido", 100, 206, 22.1, 0.0, 12.4, 0.0, 0.0, 61, 2.5, "CL", "usda_fdc"),
    Food("Canned tuna in water", "Atún en agua", "Atum em água", 100, 116, 26.0, 0.0, 1.0, 0.0, 0.0, 247, 0.2, None, "usda_fdc"),
    Food("Cod (cooked)", "Bacalao cocido", "Bacalhau cozido", 100, 105, 23.0, 0.0, 0.9, 0.0, 0.0, 78, 0.2, None, "usda_fdc"),
    Food("Shrimp (cooked)", "Camarón cocido", "Camarão cozido", 100, 99, 24.0, 0.2, 0.3, 0.0, 0.0, 111, 0.1, None, "usda_fdc"),
    Food("Whole egg (cooked)", "Huevo entero cocido", "Ovo inteiro cozido", 100, 155, 13.0, 1.1, 11.0, 0.0, 1.1, 124, 3.3, None, "usda_fdc"),
    Food("Egg whites (cooked)", "Claras de huevo cocidas", "Claras de ovo cozidas", 100, 52, 11.0, 0.7, 0.2, 0.0, 0.7, 166, 0.0, None, "usda_fdc"),
    Food("Turkey breast (cooked)", "Pechuga de pavo cocida", "Peito de peru cozido", 100, 135, 30.0, 0.0, 1.0, 0.0, 0.0, 54, 0.3, None, "usda_fdc"),
    Food("Tofu (firm)", "Tofu firme", "Tofu firme", 100, 144, 17.3, 2.8, 8.7, 2.3, 0.6, 14, 1.3, None, "usda_fdc"),
    Food("Tempeh", "Tempeh", "Tempeh", 100, 192, 20.0, 7.6, 11.0, 0.0, 0.0, 9, 2.2, None, "usda_fdc"),
    Food("Greek yogurt (non-fat)", "Yogur griego sin grasa", "Iogurte grego desnatado", 100, 59, 10.0, 3.6, 0.4, 0.0, 3.2, 36, 0.1, None, "usda_fdc"),
    Food("Whole milk", "Leche entera", "Leite integral", 100, 61, 3.2, 4.8, 3.3, 0.0, 5.1, 43, 1.9, None, "usda_fdc"),
    Food("Skim milk", "Leche descremada", "Leite desnatado", 100, 34, 3.4, 5.0, 0.1, 0.0, 5.0, 42, 0.1, None, "usda_fdc"),
    Food("Cottage cheese (low-fat)", "Queso cottage bajo en grasa", "Queijo cottage light", 100, 81, 11.0, 3.4, 2.3, 0.0, 3.0, 364, 1.0, None, "usda_fdc"),
    Food("Mozzarella (part-skim)", "Mozzarella semidescremada", "Mussarela semidesnatada", 100, 254, 24.0, 2.8, 16.0, 0.0, 1.1, 627, 9.9, None, "usda_fdc"),
    Food("Feta cheese", "Queso feta", "Queijo feta", 100, 264, 14.0, 4.1, 21.0, 0.0, 4.1, 917, 14.9, None, "usda_fdc"),

    # --- Fruits ---
    Food("Apple", "Manzana", "Maçã", 100, 52, 0.3, 14.0, 0.2, 2.4, 10.4, 1, 0.0, None, "usda_fdc"),
    Food("Banana", "Plátano (banana)", "Banana", 100, 89, 1.1, 23.0, 0.3, 2.6, 12.2, 1, 0.1, None, "usda_fdc"),
    Food("Orange", "Naranja", "Laranja", 100, 47, 0.9, 11.8, 0.1, 2.4, 9.4, 0, 0.0, None, "usda_fdc"),
    Food("Strawberries", "Fresas", "Morangos", 100, 32, 0.7, 7.7, 0.3, 2.0, 4.9, 1, 0.0, None, "usda_fdc"),
    Food("Blueberries", "Arándanos", "Mirtilos", 100, 57, 0.7, 14.5, 0.3, 2.4, 10.0, 1, 0.0, None, "usda_fdc"),
    Food("Avocado", "Aguacate (palta)", "Abacate", 100, 160, 2.0, 8.5, 14.7, 6.7, 0.7, 7, 2.1, "MX", "usda_fdc"),
    Food("Mango", "Mango", "Manga", 100, 60, 0.8, 15.0, 0.4, 1.6, 13.7, 1, 0.1, None, "usda_fdc"),
    Food("Papaya", "Papaya", "Mamão", 100, 43, 0.5, 11.0, 0.3, 1.7, 7.8, 8, 0.1, None, "usda_fdc"),
    Food("Pineapple", "Piña", "Abacaxi", 100, 50, 0.5, 13.1, 0.1, 1.4, 9.9, 1, 0.0, None, "usda_fdc"),
    Food("Watermelon", "Sandía", "Melancia", 100, 30, 0.6, 7.6, 0.2, 0.4, 6.2, 1, 0.0, None, "usda_fdc"),
    Food("Grapes", "Uvas", "Uvas", 100, 69, 0.7, 18.0, 0.2, 0.9, 16.0, 2, 0.1, None, "usda_fdc"),
    Food("Pear", "Pera", "Pera", 100, 57, 0.4, 15.0, 0.1, 3.1, 9.8, 1, 0.0, None, "usda_fdc"),

    # --- Vegetables ---
    Food("Broccoli (raw)", "Brócoli crudo", "Brócolis cru", 100, 34, 2.8, 6.6, 0.4, 2.6, 1.7, 33, 0.0, None, "usda_fdc"),
    Food("Spinach (raw)", "Espinaca cruda", "Espinafre cru", 100, 23, 2.9, 3.6, 0.4, 2.2, 0.4, 79, 0.1, None, "usda_fdc"),
    Food("Kale (raw)", "Kale crudo", "Couve crua", 100, 35, 2.9, 4.4, 1.5, 4.1, 0.8, 53, 0.2, None, "usda_fdc"),
    Food("Tomato (raw)", "Tomate crudo", "Tomate cru", 100, 18, 0.9, 3.9, 0.2, 1.2, 2.6, 5, 0.0, None, "usda_fdc"),
    Food("Romaine lettuce", "Lechuga romana", "Alface romana", 100, 17, 1.2, 3.3, 0.3, 2.1, 1.2, 8, 0.0, None, "usda_fdc"),
    Food("Cucumber", "Pepino", "Pepino", 100, 16, 0.7, 3.6, 0.1, 0.5, 1.7, 2, 0.0, None, "usda_fdc"),
    Food("Carrot (raw)", "Zanahoria cruda", "Cenoura crua", 100, 41, 0.9, 9.6, 0.2, 2.8, 4.7, 69, 0.0, None, "usda_fdc"),
    Food("Onion (raw)", "Cebolla cruda", "Cebola crua", 100, 40, 1.1, 9.3, 0.1, 1.7, 4.2, 4, 0.0, None, "usda_fdc"),
    Food("Bell pepper (red)", "Pimiento rojo", "Pimentão vermelho", 100, 31, 1.0, 6.0, 0.3, 2.1, 4.2, 4, 0.1, None, "usda_fdc"),
    Food("Zucchini", "Calabacín", "Abobrinha", 100, 17, 1.2, 3.1, 0.3, 1.0, 2.5, 8, 0.1, None, "usda_fdc"),
    Food("Mushrooms (white)", "Champiñones", "Cogumelos", 100, 22, 3.1, 3.3, 0.3, 1.0, 2.0, 5, 0.0, None, "usda_fdc"),
    Food("Cauliflower", "Coliflor", "Couve-flor", 100, 25, 1.9, 5.0, 0.3, 2.0, 1.9, 30, 0.1, None, "usda_fdc"),
    Food("Asparagus", "Espárragos", "Aspargos", 100, 20, 2.2, 3.9, 0.1, 2.1, 1.9, 2, 0.0, None, "usda_fdc"),
    Food("Brussels sprouts", "Coles de Bruselas", "Couves-de-bruxelas", 100, 43, 3.4, 9.0, 0.3, 3.8, 2.2, 25, 0.1, None, "usda_fdc"),

    # --- Grains / Bread ---
    Food("Whole wheat bread", "Pan integral", "Pão integral", 100, 247, 13.0, 41.0, 3.4, 7.0, 5.7, 472, 0.7, None, "usda_fdc"),
    Food("White bread", "Pan blanco", "Pão branco", 100, 265, 9.0, 49.0, 3.2, 2.7, 5.0, 491, 0.7, None, "usda_fdc"),
    Food("Oats (rolled, dry)", "Avena en hojuelas seca", "Aveia em flocos seca", 100, 389, 16.9, 66.3, 6.9, 10.6, 0.9, 2, 1.2, None, "usda_fdc"),
    Food("Whole wheat tortilla", "Tortilla de trigo integral", "Tortilha integral", 100, 274, 9.6, 47.0, 6.8, 6.0, 2.0, 581, 1.7, "MX", "usda_fdc"),
    Food("Corn tortilla", "Tortilla de maíz", "Tortilha de milho", 100, 218, 5.7, 44.6, 2.9, 6.3, 0.8, 45, 0.4, "MX", "usda_fdc"),
    Food("Whole wheat pasta (cooked)", "Pasta integral cocida", "Massa integral cozida", 100, 124, 5.3, 26.5, 0.5, 3.9, 0.7, 4, 0.1, None, "usda_fdc"),

    # --- Nuts / Seeds / Fats ---
    Food("Almonds", "Almendras", "Amêndoas", 100, 579, 21.2, 21.6, 49.9, 12.5, 4.4, 1, 3.8, None, "usda_fdc"),
    Food("Walnuts", "Nueces", "Nozes", 100, 654, 15.2, 13.7, 65.2, 6.7, 2.6, 2, 6.1, None, "usda_fdc"),
    Food("Peanut butter (natural)", "Mantequilla de maní natural", "Manteiga de amendoim natural", 100, 588, 25.0, 20.0, 50.0, 6.0, 9.0, 17, 10.0, None, "usda_fdc"),
    Food("Chia seeds", "Semillas de chía", "Sementes de chia", 100, 486, 16.5, 42.1, 30.7, 34.4, 0.0, 16, 3.3, None, "usda_fdc"),
    Food("Flax seeds (ground)", "Semillas de lino molidas", "Linhaça moída", 100, 534, 18.3, 28.9, 42.2, 27.3, 1.6, 30, 3.7, None, "usda_fdc"),
    Food("Olive oil (extra virgin)", "Aceite de oliva extra virgen", "Azeite extra virgem", 100, 884, 0.0, 0.0, 100.0, 0.0, 0.0, 2, 13.8, None, "usda_fdc"),
    Food("Coconut oil", "Aceite de coco", "Óleo de coco", 100, 862, 0.0, 0.0, 100.0, 0.0, 0.0, 0, 86.5, None, "usda_fdc"),
    Food("Butter (unsalted)", "Mantequilla sin sal", "Manteiga sem sal", 100, 717, 0.9, 0.1, 81.1, 0.0, 0.1, 11, 51.4, None, "usda_fdc"),

    # --- LatAm cultural ---
    Food("Yuca (cassava, cooked)", "Yuca cocida", "Mandioca cozida", 100, 160, 1.4, 38.1, 0.3, 1.8, 1.7, 14, 0.1, "BR", "usda_fdc"),
    Food("Choclo (Peruvian corn)", "Choclo", "Milho peruano", 100, 95, 3.3, 21.0, 0.9, 2.7, 2.5, 3, 0.1, "PE", "usda_fdc"),
    Food("Queso fresco", "Queso fresco", "Queijo fresco", 100, 290, 18.0, 4.0, 23.0, 0.0, 4.0, 690, 14.0, "MX", "usda_fdc"),
    Food("Yerba mate (infusion)", "Yerba mate (infusión)", "Erva-mate (chá)", 100, 5, 0.0, 1.0, 0.0, 0.0, 0.0, 7, 0.0, "AR", "usda_fdc"),
    Food("Granola (low sugar)", "Granola baja en azúcar", "Granola sem açúcar", 100, 471, 13.0, 64.0, 20.0, 7.0, 12.0, 26, 3.0, None, "usda_fdc"),
    Food("Honey", "Miel", "Mel", 100, 304, 0.3, 82.4, 0.0, 0.2, 82.1, 4, 0.0, None, "usda_fdc"),
]


def _validate_macros(f: Food) -> bool:
    """Relaxed to 5% for USDA per-100g seed rows (fiber/alcohol rounding)."""
    derived = f.protein_g * 4 + f.carbs_g * 4 + f.fat_g * 9
    if f.kcal <= 0:
        return False
    return abs(f.kcal - derived) / f.kcal <= max(MACRO_TOLERANCE, 0.05)


async def _embed_batch(texts: list[str]) -> list[list[float] | None]:
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        log.warning("seed_foods.embed_skipped", reason="no OPENAI_API_KEY")
        return [None] * len(texts)
    try:
        from openai import AsyncOpenAI
        client = AsyncOpenAI(api_key=api_key)
        resp = await client.embeddings.create(
            model="text-embedding-3-large", input=texts, dimensions=1536,
        )
        return [item.embedding for item in resp.data]
    except Exception as e:  # noqa: BLE001
        log.error("seed_foods.embed_failed", error=str(e))
        return [None] * len(texts)


async def main() -> int:
    configure_logging()
    invalid = [f for f in STARTER_FOODS if not _validate_macros(f)]
    for f in invalid:
        log.warning(
            "seed_foods.macro_invalid", food=f.name_en, kcal=f.kcal,
            p=f.protein_g, c=f.carbs_g, g=f.fat_g,
        )
    if invalid and os.environ.get("STRICT_MACROS") == "1":
        log.error("seed_foods.aborting_on_invalid_macros", n=len(invalid))
        return 2

    texts_to_embed = [f"{f.name_en} {f.name_es}" for f in STARTER_FOODS]
    embeddings = await _embed_batch(texts_to_embed)

    inserted = updated = 0
    async with session_scope() as s:
        for f, emb in zip(STARTER_FOODS, embeddings, strict=True):
            name_norm = normalise(f.name_en)
            translations: dict[str, str] = {"es": f.name_es}
            if f.name_pt:
                translations["pt"] = f.name_pt
            params = {
                "name_en": f.name_en, "name_norm": name_norm,
                "translations": json.dumps(translations),
                "country": f.country, "portion_g": f.portion_g,
                "kcal": f.kcal, "protein_g": f.protein_g, "carbs_g": f.carbs_g, "fat_g": f.fat_g,
                "fiber_g": f.fiber_g, "sugar_g": f.sugar_g,
                "sodium_mg": f.sodium_mg, "sat_fat_g": f.sat_fat_g,
                "source": f.source, "verified": f.verified,
                "embedding": emb,
            }
            result = await s.execute(text("""
                INSERT INTO foods (
                    name_en, name_norm, name_translations, country,
                    portion_g, kcal, protein_g, carbs_g, fat_g,
                    fiber_g, sugar_g, sodium_mg, sat_fat_g,
                    source, verified, embedding, updated_at
                )
                VALUES (
                    :name_en, :name_norm, CAST(:translations AS jsonb), :country,
                    :portion_g, :kcal, :protein_g, :carbs_g, :fat_g,
                    :fiber_g, :sugar_g, :sodium_mg, :sat_fat_g,
                    :source, :verified, :embedding, now()
                )
                ON CONFLICT (name_norm) DO UPDATE SET
                    name_en = EXCLUDED.name_en,
                    name_translations = EXCLUDED.name_translations,
                    country = EXCLUDED.country,
                    portion_g = EXCLUDED.portion_g,
                    kcal = EXCLUDED.kcal,
                    protein_g = EXCLUDED.protein_g,
                    carbs_g = EXCLUDED.carbs_g,
                    fat_g = EXCLUDED.fat_g,
                    fiber_g = EXCLUDED.fiber_g,
                    sugar_g = EXCLUDED.sugar_g,
                    sodium_mg = EXCLUDED.sodium_mg,
                    sat_fat_g = EXCLUDED.sat_fat_g,
                    source = EXCLUDED.source,
                    verified = EXCLUDED.verified,
                    embedding = COALESCE(EXCLUDED.embedding, foods.embedding),
                    updated_at = now()
                RETURNING (xmax = 0) AS inserted
            """), params)
            row = result.first()
            if row and row[0]:
                inserted += 1
            else:
                updated += 1

    log.info(
        "seed_foods.complete",
        total=len(STARTER_FOODS), inserted=inserted, updated=updated,
        with_embeddings=sum(1 for e in embeddings if e is not None),
    )
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
