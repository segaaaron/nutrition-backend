"""Round 2 catalog generation — gap closure round 2 (2026-06-01).

Targets (≈1,000 NEW recipes):
- Bucket A: Breakfast omnivore +500 (variety: huevos rancheros, omelet, pancakes proteicos,
  French toast integral, breakfast burrito, savoury oatmeal, frittata, croque-monsieur light...).
- Bucket B: CKD recommends +100 (hard gates: protein≤25, K≤400, P≤300, sodium≤500).
- Bucket C: Lactation +200 (pregnancy_safe, folate_ug≥150, calcium_mg≥300, iron_mg≥4,
  kcal 450-700, NO raw fish / soft cheese / Hg-fish / liver / alcohol / raw egg).
- Bucket D: Weight_gain dinners +200 (kcal 700-1200, protein≥35, carbs≥70).

Hard validators (mirror gap_closure):
- Macro math |kcal − (4P+4C+9F)| / kcal ≤ 0.05
- Closed vocabularies (allergens, conditions, goals, activity, regions, meal_time)
- Macro plausibility kcal [100,1500]; protein [0,80]; carbs [0,200]; fat [0,80]
- Dedup signature (sha1 over name_norm + sorted core ingredient nouns)
- Cell exact-name dedup vs full catalog + new buckets
- Bucket-specific clinical gates
- Lactation: pregnancy-unsafe ingredient detection (hard reject)

Outputs:
- data/meals/round2_batch_2026_06_01.json
- scripts/generate_recipes_round2_2026_06_01_rejections.log
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from itertools import product
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.shared.domain.vocabularies import (  # noqa: E402
    ACTIVITY_LEVELS_5, ALLERGENS_14, CONDITIONS_25, GOALS_5, MEAL_TIMES_4, REGIONS_5,
)

PLACEHOLDER_IMG = "https://storage.googleapis.com/nova-nutrition-public/placeholder.webp"
SOURCE_CATALOG = "nova_v2_batch_round2_2026_06_01"
EXISTING_CATALOG = ROOT / "data" / "meals" / "nova_meals_catalog.cleaned.json"
OUT = ROOT / "data" / "meals" / "round2_batch_2026_06_01.json"
LOG = ROOT / "scripts" / "generate_recipes_round2_2026_06_01_rejections.log"

# ---------------------------------------------------------------------------
# Ingredient table per 100 g cooked.
# Adds folate_ug, calcium_mg, iron_mg for lactation bucket gates.
# Sources: USDA FDC + BEDCA averages, rounded conservatively.
# ---------------------------------------------------------------------------
ING: dict[str, dict] = {
    # --- Animal proteins (lactation-safe = fully cooked) ---
    "pollo_pechuga":    {"kcal":165,"p":31,"c":0,"f":3.6,"fib":0,"sug":0,"na":74,"gi":0,"satfat":1.0,"k":256,"ph":220,"fol":4,"ca":15,"fe":1.0,"tags":["omnivore","pescatarian"]},
    "pavo_pechuga":     {"kcal":135,"p":30,"c":0,"f":1.0,"fib":0,"sug":0,"na":65,"gi":0,"satfat":0.3,"k":239,"ph":210,"fol":6,"ca":12,"fe":1.4,"tags":["omnivore","pescatarian"]},
    "salmon":           {"kcal":208,"p":22,"c":0,"f":13,"fib":0,"sug":0,"na":59,"gi":0,"satfat":3.1,"k":363,"ph":240,"fol":26,"ca":12,"fe":0.8,"tags":["omnivore","pescatarian"],"allergens":["fish"]},
    "atun_lata_agua":   {"kcal":116,"p":26,"c":0,"f":0.8,"fib":0,"sug":0,"na":247,"gi":0,"satfat":0.2,"k":237,"ph":158,"fol":4,"ca":11,"fe":1.4,"tags":["omnivore","pescatarian"],"allergens":["fish"]},
    "bacalao":          {"kcal":82,"p":18,"c":0,"f":0.7,"fib":0,"sug":0,"na":78,"gi":0,"satfat":0.1,"k":244,"ph":138,"fol":7,"ca":14,"fe":0.4,"tags":["omnivore","pescatarian"],"allergens":["fish"]},
    "merluza":          {"kcal":86,"p":18,"c":0,"f":1.3,"fib":0,"sug":0,"na":75,"gi":0,"satfat":0.2,"k":280,"ph":195,"fol":11,"ca":18,"fe":0.4,"tags":["omnivore","pescatarian"],"allergens":["fish"]},
    "lenguado":         {"kcal":91,"p":19,"c":0,"f":1.2,"fib":0,"sug":0,"na":81,"gi":0,"satfat":0.2,"k":286,"ph":195,"fol":11,"ca":18,"fe":0.4,"tags":["omnivore","pescatarian"],"allergens":["fish"]},
    "huevo":            {"kcal":143,"p":13,"c":1.1,"f":9.5,"fib":0,"sug":1.1,"na":142,"gi":0,"satfat":3.0,"k":138,"ph":198,"fol":47,"ca":56,"fe":1.8,"tags":["omnivore","pescatarian","vegetarian"],"allergens":["egg"]},
    "clara_huevo":      {"kcal":52,"p":11,"c":0.7,"f":0.2,"fib":0,"sug":0.7,"na":166,"gi":0,"satfat":0.0,"k":163,"ph":15,"fol":4,"ca":7,"fe":0.1,"tags":["omnivore","pescatarian","vegetarian"],"allergens":["egg"]},
    "lomo_magro":       {"kcal":158,"p":26,"c":0,"f":6,"fib":0,"sug":0,"na":60,"gi":0,"satfat":2.0,"k":340,"ph":220,"fol":3,"ca":15,"fe":1.5,"tags":["omnivore"]},
    "carne_magra_res":  {"kcal":182,"p":27,"c":0,"f":8,"fib":0,"sug":0,"na":65,"gi":0,"satfat":3.2,"k":318,"ph":200,"fol":7,"ca":18,"fe":2.6,"tags":["omnivore"]},
    "carne_molida_res": {"kcal":215,"p":26,"c":0,"f":12,"fib":0,"sug":0,"na":75,"gi":0,"satfat":4.7,"k":290,"ph":190,"fol":8,"ca":18,"fe":2.7,"tags":["omnivore"]},
    "cordero":          {"kcal":250,"p":25,"c":0,"f":16,"fib":0,"sug":0,"na":72,"gi":0,"satfat":7.5,"k":310,"ph":190,"fol":18,"ca":17,"fe":1.9,"tags":["omnivore"]},
    "camaron":          {"kcal":99,"p":24,"c":0.2,"f":0.3,"fib":0,"sug":0,"na":111,"gi":0,"satfat":0.1,"k":259,"ph":214,"fol":5,"ca":70,"fe":0.5,"tags":["omnivore","pescatarian"],"allergens":["shellfish"]},
    "jamon_serrano":    {"kcal":195,"p":31,"c":0,"f":8,"fib":0,"sug":0,"na":1090,"gi":0,"satfat":2.8,"k":336,"ph":205,"fol":4,"ca":14,"fe":1.0,"tags":["omnivore"]},
    "bacon_pavo":       {"kcal":190,"p":26,"c":1,"f":9,"fib":0,"sug":0,"na":1100,"gi":0,"satfat":2.5,"k":280,"ph":190,"fol":4,"ca":10,"fe":1.0,"tags":["omnivore"]},
    "yogur_griego":     {"kcal":59,"p":10,"c":3.6,"f":0.4,"fib":0,"sug":3.2,"na":36,"gi":11,"satfat":0.1,"k":141,"ph":135,"fol":7,"ca":110,"fe":0.0,"tags":["omnivore","pescatarian","vegetarian"],"allergens":["dairy"]},
    "queso_cottage":    {"kcal":98,"p":11,"c":3.4,"f":4.3,"fib":0,"sug":2.7,"na":364,"gi":30,"satfat":1.7,"k":104,"ph":160,"fol":12,"ca":83,"fe":0.1,"tags":["omnivore","pescatarian","vegetarian"],"allergens":["dairy"]},
    "queso_fresco":     {"kcal":140,"p":11,"c":4,"f":9,"fib":0,"sug":4,"na":350,"gi":30,"satfat":5.0,"k":127,"ph":174,"fol":14,"ca":290,"fe":0.2,"tags":["omnivore","pescatarian","vegetarian"],"allergens":["dairy"]},
    "queso_mozzarella": {"kcal":280,"p":28,"c":3,"f":17,"fib":0,"sug":1,"na":620,"gi":30,"satfat":10,"k":76,"ph":350,"fol":7,"ca":505,"fe":0.4,"tags":["omnivore","pescatarian","vegetarian"],"allergens":["dairy"]},
    "queso_cheddar":    {"kcal":403,"p":25,"c":1.3,"f":33,"fib":0,"sug":0.5,"na":621,"gi":30,"satfat":21,"k":98,"ph":512,"fol":18,"ca":721,"fe":0.7,"tags":["omnivore","pescatarian","vegetarian"],"allergens":["dairy"]},
    "queso_parmesano":  {"kcal":392,"p":36,"c":3.2,"f":26,"fib":0,"sug":0.8,"na":1602,"gi":30,"satfat":17,"k":92,"ph":694,"fol":7,"ca":1184,"fe":0.8,"tags":["omnivore","pescatarian","vegetarian"],"allergens":["dairy"]},
    "leche_entera":     {"kcal":61,"p":3.2,"c":4.8,"f":3.3,"fib":0,"sug":5.1,"na":43,"gi":30,"satfat":1.9,"k":150,"ph":93,"fol":5,"ca":113,"fe":0.0,"tags":["omnivore","pescatarian","vegetarian"],"allergens":["dairy"]},
    # --- Plant proteins ---
    "tofu_firme":       {"kcal":144,"p":17,"c":3,"f":9,"fib":2,"sug":1,"na":14,"gi":15,"satfat":1.3,"k":121,"ph":190,"fol":29,"ca":350,"fe":2.7,"tags":["any"],"allergens":["soy"]},
    "tempeh":           {"kcal":192,"p":20,"c":8,"f":11,"fib":0,"sug":0,"na":9,"gi":15,"satfat":2.2,"k":412,"ph":266,"fol":24,"ca":111,"fe":2.7,"tags":["any"],"allergens":["soy"]},
    "lentejas":         {"kcal":116,"p":9,"c":20,"f":0.4,"fib":8,"sug":1.8,"na":2,"gi":32,"satfat":0.1,"k":369,"ph":180,"fol":181,"ca":19,"fe":3.3,"tags":["any"]},
    "garbanzos":        {"kcal":164,"p":8.9,"c":27,"f":2.6,"fib":7.6,"sug":4.8,"na":7,"gi":28,"satfat":0.3,"k":291,"ph":168,"fol":172,"ca":49,"fe":2.9,"tags":["any"]},
    "frijoles_negros":  {"kcal":132,"p":8.9,"c":24,"f":0.5,"fib":8.7,"sug":0.3,"na":1,"gi":30,"satfat":0.1,"k":355,"ph":140,"fol":149,"ca":27,"fe":2.1,"tags":["any"]},
    "frijoles_rojos":   {"kcal":127,"p":8.7,"c":23,"f":0.5,"fib":7.4,"sug":0.3,"na":1,"gi":30,"satfat":0.1,"k":403,"ph":138,"fol":130,"ca":28,"fe":2.2,"tags":["any"]},
    "edamame":          {"kcal":121,"p":12,"c":9,"f":5,"fib":5,"sug":2.2,"na":6,"gi":18,"satfat":0.6,"k":436,"ph":169,"fol":311,"ca":63,"fe":2.3,"tags":["any"],"allergens":["soy"]},
    # --- Carbs ---
    "quinoa":           {"kcal":120,"p":4.4,"c":21,"f":1.9,"fib":2.8,"sug":0.9,"na":7,"gi":53,"satfat":0.2,"k":172,"ph":152,"fol":42,"ca":17,"fe":1.5,"tags":["any"]},
    "arroz_integral":   {"kcal":123,"p":2.7,"c":26,"f":1.0,"fib":1.6,"sug":0.4,"na":4,"gi":50,"satfat":0.3,"k":79,"ph":83,"fol":4,"ca":3,"fe":0.4,"tags":["any"]},
    "arroz_blanco":     {"kcal":130,"p":2.7,"c":28,"f":0.3,"fib":0.4,"sug":0.1,"na":1,"gi":73,"satfat":0.1,"k":35,"ph":43,"fol":58,"ca":10,"fe":1.2,"tags":["any"]},
    "arroz_basmati":    {"kcal":121,"p":3,"c":25,"f":0.4,"fib":0.4,"sug":0,"na":3,"gi":58,"satfat":0.1,"k":35,"ph":43,"fol":5,"ca":3,"fe":0.4,"tags":["any"]},
    "camote":           {"kcal":86,"p":1.6,"c":20,"f":0.1,"fib":3,"sug":4.2,"na":55,"gi":63,"satfat":0.0,"k":337,"ph":47,"fol":11,"ca":30,"fe":0.6,"tags":["any"]},
    "papa_blanca":      {"kcal":77,"p":2,"c":17,"f":0.1,"fib":2.2,"sug":0.8,"na":6,"gi":78,"satfat":0.0,"k":421,"ph":57,"fol":15,"ca":12,"fe":0.8,"tags":["any"]},
    "polenta":          {"kcal":70,"p":1.5,"c":15,"f":0.3,"fib":1,"sug":0,"na":1,"gi":68,"satfat":0.0,"k":21,"ph":22,"fol":5,"ca":2,"fe":0.4,"tags":["any"]},
    "tortilla_maiz":    {"kcal":218,"p":5.7,"c":45,"f":2.9,"fib":6.3,"sug":1.1,"na":45,"gi":52,"satfat":0.4,"k":186,"ph":314,"fol":5,"ca":81,"fe":1.2,"tags":["any"]},
    "tortilla_trigo":   {"kcal":290,"p":8,"c":49,"f":7,"fib":2.8,"sug":2,"na":681,"gi":55,"satfat":1.8,"k":120,"ph":120,"fol":140,"ca":140,"fe":3.0,"tags":["any"],"allergens":["gluten"]},
    "pan_integral":     {"kcal":247,"p":13,"c":41,"f":3.5,"fib":7,"sug":4.4,"na":472,"gi":51,"satfat":0.7,"k":248,"ph":228,"fol":42,"ca":107,"fe":2.5,"tags":["any"],"allergens":["gluten"]},
    "pan_brioche":      {"kcal":346,"p":10,"c":46,"f":13,"fib":1.5,"sug":7,"na":420,"gi":70,"satfat":7.5,"k":110,"ph":110,"fol":110,"ca":40,"fe":2.5,"tags":["any"],"allergens":["gluten","egg","dairy"]},
    "avena":            {"kcal":71,"p":2.5,"c":12,"f":1.5,"fib":1.7,"sug":0,"na":3,"gi":55,"satfat":0.3,"k":70,"ph":80,"fol":7,"ca":9,"fe":0.9,"tags":["any"],"allergens":["gluten"]},
    "avena_seca":       {"kcal":389,"p":17,"c":66,"f":7,"fib":11,"sug":0,"na":2,"gi":55,"satfat":1.2,"k":429,"ph":523,"fol":56,"ca":54,"fe":4.7,"tags":["any"],"allergens":["gluten"]},
    "harina_avena":     {"kcal":404,"p":15,"c":66,"f":9,"fib":7,"sug":1,"na":3,"gi":55,"satfat":1.5,"k":360,"ph":400,"fol":32,"ca":55,"fe":4.0,"tags":["any"],"allergens":["gluten"]},
    "pasta_integral":   {"kcal":124,"p":5,"c":25,"f":1,"fib":3.5,"sug":1,"na":5,"gi":50,"satfat":0.2,"k":62,"ph":105,"fol":7,"ca":15,"fe":1.3,"tags":["any"],"allergens":["gluten"]},
    "pasta_blanca":     {"kcal":131,"p":5,"c":25,"f":1.1,"fib":1.8,"sug":0.6,"na":1,"gi":58,"satfat":0.2,"k":44,"ph":58,"fol":83,"ca":7,"fe":1.3,"tags":["any"],"allergens":["gluten"]},
    "fideos_arroz":     {"kcal":109,"p":1.8,"c":25,"f":0.2,"fib":1,"sug":0.1,"na":19,"gi":61,"satfat":0.0,"k":4,"ph":14,"fol":2,"ca":4,"fe":0.2,"tags":["any"]},
    "platano_macho":    {"kcal":122,"p":1.3,"c":32,"f":0.4,"fib":2.3,"sug":15,"na":4,"gi":55,"satfat":0.1,"k":499,"ph":34,"fol":22,"ca":3,"fe":0.6,"tags":["any"]},
    "yuca":             {"kcal":160,"p":1.4,"c":38,"f":0.3,"fib":1.8,"sug":1.7,"na":14,"gi":55,"satfat":0.1,"k":271,"ph":27,"fol":27,"ca":16,"fe":0.3,"tags":["any"]},
    # --- Vegetables ---
    "espinaca":         {"kcal":23,"p":2.9,"c":3.6,"f":0.4,"fib":2.2,"sug":0.4,"na":79,"gi":15,"satfat":0.1,"k":558,"ph":49,"fol":194,"ca":99,"fe":2.7,"tags":["any"]},
    "brocoli":          {"kcal":35,"p":2.4,"c":7,"f":0.4,"fib":3.3,"sug":1.7,"na":41,"gi":15,"satfat":0.0,"k":316,"ph":66,"fol":108,"ca":40,"fe":0.7,"tags":["any"]},
    "kale":             {"kcal":35,"p":2.9,"c":4.4,"f":1.5,"fib":4.1,"sug":0.8,"na":53,"gi":15,"satfat":0.2,"k":348,"ph":55,"fol":141,"ca":150,"fe":1.5,"tags":["any"]},
    "tomate":           {"kcal":18,"p":0.9,"c":3.9,"f":0.2,"fib":1.2,"sug":2.6,"na":5,"gi":30,"satfat":0.0,"k":237,"ph":24,"fol":15,"ca":10,"fe":0.3,"tags":["any"]},
    "pimiento_rojo":    {"kcal":31,"p":1,"c":6,"f":0.3,"fib":2.1,"sug":4.2,"na":4,"gi":15,"satfat":0.1,"k":211,"ph":26,"fol":46,"ca":7,"fe":0.4,"tags":["any"]},
    "calabacin":        {"kcal":17,"p":1.2,"c":3.1,"f":0.3,"fib":1,"sug":2.5,"na":8,"gi":15,"satfat":0.1,"k":261,"ph":38,"fol":24,"ca":16,"fe":0.4,"tags":["any"]},
    "zanahoria":        {"kcal":41,"p":0.9,"c":9.6,"f":0.2,"fib":2.8,"sug":4.7,"na":69,"gi":39,"satfat":0.0,"k":320,"ph":35,"fol":19,"ca":33,"fe":0.3,"tags":["any"]},
    "cebolla":          {"kcal":40,"p":1.1,"c":9.3,"f":0.1,"fib":1.7,"sug":4.2,"na":4,"gi":15,"satfat":0.0,"k":146,"ph":29,"fol":19,"ca":23,"fe":0.2,"tags":["any"]},
    "champinones":      {"kcal":22,"p":3.1,"c":3.3,"f":0.3,"fib":1,"sug":2,"na":5,"gi":15,"satfat":0.0,"k":318,"ph":86,"fol":17,"ca":3,"fe":0.5,"tags":["any"]},
    "aguacate":         {"kcal":160,"p":2,"c":9,"f":15,"fib":7,"sug":0.7,"na":7,"gi":10,"satfat":2.1,"k":485,"ph":52,"fol":81,"ca":12,"fe":0.6,"tags":["any"]},
    "pepino":           {"kcal":16,"p":0.7,"c":3.6,"f":0.1,"fib":0.5,"sug":1.7,"na":2,"gi":15,"satfat":0.0,"k":147,"ph":24,"fol":7,"ca":16,"fe":0.3,"tags":["any"]},
    "lechuga":          {"kcal":15,"p":1.4,"c":2.9,"f":0.2,"fib":1.3,"sug":0.8,"na":28,"gi":15,"satfat":0.0,"k":194,"ph":29,"fol":38,"ca":18,"fe":0.4,"tags":["any"]},
    "repollo":          {"kcal":25,"p":1.3,"c":5.8,"f":0.1,"fib":2.5,"sug":3.2,"na":18,"gi":15,"satfat":0.0,"k":170,"ph":26,"fol":43,"ca":40,"fe":0.5,"tags":["any"]},
    "judias_verdes":    {"kcal":31,"p":1.8,"c":7,"f":0.2,"fib":2.7,"sug":3.3,"na":6,"gi":32,"satfat":0.0,"k":211,"ph":38,"fol":33,"ca":37,"fe":1.0,"tags":["any"]},
    "esparragos":       {"kcal":20,"p":2.2,"c":3.9,"f":0.1,"fib":2.1,"sug":1.9,"na":2,"gi":15,"satfat":0.0,"k":202,"ph":52,"fol":52,"ca":24,"fe":2.1,"tags":["any"]},
    "salsa_tomate":     {"kcal":33,"p":1.5,"c":7,"f":0.2,"fib":2,"sug":4,"na":350,"gi":35,"satfat":0.0,"k":297,"ph":32,"fol":10,"ca":13,"fe":0.7,"tags":["any"]},
    # --- Fats / nuts / seeds / fruits ---
    "aceite_oliva":     {"kcal":884,"p":0,"c":0,"f":100,"fib":0,"sug":0,"na":2,"gi":0,"satfat":14,"k":1,"ph":0,"fol":0,"ca":1,"fe":0.6,"tags":["any"]},
    "mantequilla":      {"kcal":717,"p":0.9,"c":0.1,"f":81,"fib":0,"sug":0.1,"na":11,"gi":0,"satfat":51,"k":24,"ph":24,"fol":3,"ca":24,"fe":0.0,"tags":["any"],"allergens":["dairy"]},
    "almendras":        {"kcal":579,"p":21,"c":22,"f":50,"fib":12,"sug":4.4,"na":1,"gi":0,"satfat":3.8,"k":733,"ph":481,"fol":44,"ca":269,"fe":3.7,"tags":["any"],"allergens":["tree_nuts"]},
    "nuez":             {"kcal":654,"p":15,"c":14,"f":65,"fib":6.7,"sug":2.6,"na":2,"gi":0,"satfat":6.1,"k":441,"ph":346,"fol":98,"ca":98,"fe":2.9,"tags":["any"],"allergens":["tree_nuts"]},
    "semillas_chia":    {"kcal":486,"p":17,"c":42,"f":31,"fib":34,"sug":0,"na":16,"gi":1,"satfat":3.3,"k":407,"ph":860,"fol":49,"ca":631,"fe":7.7,"tags":["any"]},
    "semillas_lino":    {"kcal":534,"p":18,"c":29,"f":42,"fib":27,"sug":1.6,"na":30,"gi":1,"satfat":3.7,"k":813,"ph":642,"fol":87,"ca":255,"fe":5.7,"tags":["any"]},
    "manzana":          {"kcal":52,"p":0.3,"c":14,"f":0.2,"fib":2.4,"sug":10,"na":1,"gi":36,"satfat":0.0,"k":107,"ph":11,"fol":3,"ca":6,"fe":0.1,"tags":["any"]},
    "pera":             {"kcal":57,"p":0.4,"c":15,"f":0.1,"fib":3.1,"sug":9.8,"na":1,"gi":38,"satfat":0.0,"k":116,"ph":12,"fol":7,"ca":9,"fe":0.2,"tags":["any"]},
    "arandanos":        {"kcal":57,"p":0.7,"c":14,"f":0.3,"fib":2.4,"sug":10,"na":1,"gi":53,"satfat":0.0,"k":77,"ph":12,"fol":6,"ca":6,"fe":0.3,"tags":["any"]},
    "frutos_rojos":     {"kcal":50,"p":1,"c":12,"f":0.3,"fib":3,"sug":8,"na":1,"gi":32,"satfat":0.0,"k":153,"ph":24,"fol":24,"ca":16,"fe":0.4,"tags":["any"]},
    "platano_fruta":    {"kcal":89,"p":1.1,"c":23,"f":0.3,"fib":2.6,"sug":12,"na":1,"gi":51,"satfat":0.1,"k":358,"ph":22,"fol":20,"ca":5,"fe":0.3,"tags":["any"]},
    "miel_maple":       {"kcal":260,"p":0,"c":67,"f":0.2,"fib":0,"sug":60,"na":12,"gi":54,"satfat":0.0,"k":204,"ph":2,"fol":0,"ca":102,"fe":0.1,"tags":["any"]},
}

ALLERGEN_FROM_KEY = {k: tuple(v.get("allergens", [])) for k, v in ING.items()}

DISPLAY = {
    "pollo_pechuga": "Pollo", "pavo_pechuga": "Pavo",
    "salmon": "Salmón", "atun_lata_agua": "Atún en Agua",
    "bacalao": "Bacalao", "merluza": "Merluza", "lenguado": "Lenguado",
    "huevo": "Huevo", "clara_huevo": "Claras de Huevo",
    "lomo_magro": "Lomo Magro", "carne_magra_res": "Res Magra",
    "carne_molida_res": "Res Molida", "cordero": "Cordero",
    "camaron": "Camarones", "jamon_serrano": "Jamón Serrano",
    "bacon_pavo": "Bacon de Pavo",
    "yogur_griego": "Yogur Griego", "queso_cottage": "Cottage",
    "queso_fresco": "Queso Fresco", "queso_mozzarella": "Mozzarella",
    "queso_cheddar": "Cheddar", "queso_parmesano": "Parmesano",
    "leche_entera": "Leche",
    "tofu_firme": "Tofu", "tempeh": "Tempeh",
    "lentejas": "Lentejas", "garbanzos": "Garbanzos",
    "frijoles_negros": "Frijoles Negros", "frijoles_rojos": "Frijoles Rojos",
    "edamame": "Edamame",
    "quinoa": "Quinoa", "arroz_integral": "Arroz Integral",
    "arroz_blanco": "Arroz Blanco", "arroz_basmati": "Arroz Basmati",
    "camote": "Camote", "papa_blanca": "Papa Blanca", "polenta": "Polenta",
    "tortilla_maiz": "Tortilla de Maíz", "tortilla_trigo": "Tortilla de Trigo",
    "pan_integral": "Pan Integral", "pan_brioche": "Pan Brioche",
    "avena": "Avena", "avena_seca": "Avena en Hojuelas",
    "harina_avena": "Harina de Avena",
    "pasta_integral": "Pasta Integral", "pasta_blanca": "Pasta Blanca",
    "fideos_arroz": "Fideos de Arroz",
    "platano_macho": "Plátano Macho", "yuca": "Yuca",
    "espinaca": "Espinaca", "brocoli": "Brócoli", "kale": "Kale",
    "tomate": "Tomate", "pimiento_rojo": "Pimiento Rojo",
    "calabacin": "Calabacín", "zanahoria": "Zanahoria",
    "cebolla": "Cebolla", "champinones": "Champiñones",
    "aguacate": "Aguacate", "pepino": "Pepino", "lechuga": "Lechuga",
    "repollo": "Repollo", "judias_verdes": "Judías Verdes",
    "esparragos": "Espárragos", "salsa_tomate": "Salsa de Tomate",
    "aceite_oliva": "Aceite de Oliva", "mantequilla": "Mantequilla",
    "almendras": "Almendras", "nuez": "Nueces",
    "semillas_chia": "Chía", "semillas_lino": "Linaza",
    "manzana": "Manzana", "pera": "Pera",
    "arandanos": "Arándanos", "frutos_rojos": "Frutos Rojos",
    "platano_fruta": "Plátano", "miel_maple": "Miel de Maple",
}


def _t(tid, cuisine, mt, diet, prot_pool, prot_g, carb_pool, carb_g, veg_pool, veg_g,
       fat_pool, fat_g, name, desc, regions, rec, contra, goals, act, preg,
       prep, cook, origin, instructions, bucket="generic"):
    return {
        "tid": tid, "cuisine": cuisine, "meal_time": mt, "diet": diet,
        "prot_pool": prot_pool, "prot_g": prot_g,
        "carb_pool": carb_pool, "carb_g": carb_g,
        "veg_pool": veg_pool, "veg_g": veg_g,
        "fat_pool": fat_pool, "fat_g": fat_g,
        "name": name, "desc": desc,
        "regions": regions, "rec": rec, "contra": contra,
        "goals": goals, "act": act, "preg": preg,
        "prep": prep, "cook": cook, "origin": origin,
        "instructions": instructions, "bucket": bucket,
    }


# ---------------------------------------------------------------------------
# Bucket A — Breakfast omnivore +500
# ---------------------------------------------------------------------------
BREAKFAST_OMNI = [
    _t("bfo_huevos_rancheros", ["latam"], "breakfast", "omnivore",
       ["huevo"], 120,
       ["tortilla_maiz","tortilla_trigo","arroz_blanco"], 50,
       ["tomate","pimiento_rojo","cebolla","aguacate","frijoles_negros"], 80,
       ["aceite_oliva","queso_fresco","aguacate"], 12,
       "Huevos Rancheros con {carb}, {veg} y {fat}",
       "Desayuno mexicano clásico con huevo, salsa ranchera y tortilla.",
       ["latam","us"], ["athletic_load"], [],
       ["maintain","muscle_gain"], ["lightly_active","moderately_active","very_active"],
       True, 8, 8, "México",
       ["Cocina los {prot} estrellados.","Calienta el {carb}.","Saltea {veg} con salsa.","Termina con {fat}."],
       bucket="bf_omni"),
    _t("bfo_omelet_clasica", ["mediterranean","north_american","european"], "breakfast", "omnivore",
       ["huevo","clara_huevo"], 130,
       ["pan_integral","tortilla_trigo","papa_blanca"], 50,
       ["espinaca","champinones","tomate","pimiento_rojo","cebolla","brocoli"], 80,
       ["aceite_oliva","queso_mozzarella","queso_cheddar","mantequilla"], 12,
       "Omelet de {prot} con {veg}, {carb} y {fat}",
       "Omelet francés clásico con vegetales salteados y proteína completa.",
       ["us","eu","uk","ca"], ["athletic_load"], [],
       ["maintain","muscle_gain","weight_loss"], ["lightly_active","moderately_active","very_active"],
       True, 8, 6, "Francia/USA",
       ["Bate los {prot}.","Saltea {veg}.","Vierte el huevo y cocina.","Sirve con {carb}.","Termina con {fat}."],
       bucket="bf_omni"),
    _t("bfo_pancakes_proteicos", ["north_american"], "breakfast", "omnivore",
       ["huevo","yogur_griego","queso_cottage"], 100,
       ["avena","harina_avena","platano_fruta"], 60,
       ["arandanos","frutos_rojos","manzana","pera"], 70,
       ["almendras","nuez","semillas_chia","mantequilla"], 12,
       "Pancakes Proteicos con {carb}, {veg} y {fat}",
       "Pancakes altos en proteína con avena y frutos rojos.",
       ["us","ca","eu","uk","latam"], ["athletic_load"], [],
       ["muscle_gain","maintain","weight_gain"], ["lightly_active","moderately_active","very_active"],
       True, 8, 10, "USA fitness",
       ["Mezcla {prot}, {carb} y leche.","Cocina en sartén.","Acompaña con {veg}.","Termina con {fat}."],
       bucket="bf_omni"),
    _t("bfo_french_toast_integral", ["north_american","european"], "breakfast", "omnivore",
       ["huevo","leche_entera"], 100,
       ["pan_integral","pan_brioche"], 60,
       ["arandanos","frutos_rojos","manzana","platano_fruta"], 70,
       ["nuez","almendras","semillas_chia","miel_maple"], 12,
       "French Toast Integral con {veg} y {fat}",
       "French toast integral con frutas y grasas saludables.",
       ["us","ca","eu","uk"], [], [],
       ["maintain","muscle_gain","weight_gain"], ["lightly_active","moderately_active","very_active"],
       True, 5, 8, "Francia/USA",
       ["Bate {prot} con leche.","Empapa el {carb}.","Cocina dorando.","Acompaña con {veg}.","Termina con {fat}."],
       bucket="bf_omni"),
    _t("bfo_breakfast_burrito", ["latam","north_american"], "breakfast", "omnivore",
       ["huevo","pollo_pechuga","pavo_pechuga","carne_magra_res","bacon_pavo"], 110,
       ["tortilla_trigo","tortilla_maiz","arroz_blanco"], 50,
       ["frijoles_negros","aguacate","tomate","pimiento_rojo","cebolla","espinaca"], 80,
       ["aceite_oliva","aguacate","queso_cheddar","queso_mozzarella"], 12,
       "Breakfast Burrito de {prot} con {carb}, {veg} y {fat}",
       "Breakfast burrito tex-mex con proteína magra y vegetales.",
       ["us","ca","latam"], ["athletic_load"], [],
       ["muscle_gain","maintain","weight_gain"], ["lightly_active","moderately_active","very_active"],
       True, 8, 8, "TexMex",
       ["Cocina el {prot}.","Calienta el {carb}.","Saltea {veg}.","Enrolla.","Termina con {fat}."],
       bucket="bf_omni"),
    _t("bfo_savory_oatmeal", ["north_american","european"], "breakfast", "omnivore",
       ["huevo","jamon_serrano","pollo_pechuga","pavo_pechuga"], 90,
       ["avena","avena_seca","harina_avena"], 50,
       ["espinaca","champinones","tomate","aguacate","brocoli"], 80,
       ["aceite_oliva","queso_parmesano","aguacate","mantequilla"], 10,
       "Savory Oatmeal con {prot}, {veg} y {fat}",
       "Avena salada con huevo y vegetales — desayuno proteico moderno.",
       ["us","eu","uk","ca"], ["athletic_load","dyslipidemia"], [],
       ["maintain","muscle_gain","weight_loss"], ["lightly_active","moderately_active","very_active"],
       True, 5, 10, "USA wellness",
       ["Cocina {carb} con agua.","Añade {prot} cocido.","Saltea {veg}.","Termina con {fat}."],
       bucket="bf_omni"),
    _t("bfo_frittata", ["mediterranean","european"], "breakfast", "omnivore",
       ["huevo","jamon_serrano","pollo_pechuga","queso_mozzarella"], 130,
       ["papa_blanca","camote","pan_integral"], 50,
       ["espinaca","champinones","calabacin","tomate","pimiento_rojo","esparragos"], 90,
       ["aceite_oliva","queso_parmesano","mantequilla"], 12,
       "Frittata de {prot} con {veg}, {carb} y {fat}",
       "Frittata italiana al horno con vegetales y queso.",
       ["eu","us","uk","latam"], ["athletic_load"], [],
       ["maintain","muscle_gain"], ["lightly_active","moderately_active","very_active"],
       True, 10, 15, "Italia",
       ["Bate {prot}.","Saltea {veg}.","Vierte y hornea.","Sirve con {carb}.","Termina con {fat}."],
       bucket="bf_omni"),
    _t("bfo_croque_light", ["european"], "breakfast", "omnivore",
       ["jamon_serrano","pavo_pechuga","huevo"], 90,
       ["pan_integral","pan_brioche"], 60,
       ["espinaca","tomate","champinones"], 60,
       ["queso_mozzarella","queso_cheddar","mantequilla","aceite_oliva"], 12,
       "Croque-Monsieur Light con {prot}, {carb} y {fat}",
       "Croque-monsieur ligero con jamón y queso fundido.",
       ["eu","fr","us"], [], ["hypertension"],
       ["maintain","muscle_gain"], ["lightly_active","moderately_active","very_active"],
       True, 5, 10, "Francia",
       ["Tuesta {carb}.","Coloca {prot}.","Cubre con {fat}.","Gratina.","Acompaña con {veg}."],
       bucket="bf_omni"),
    _t("bfo_huevos_divorciados", ["latam"], "breakfast", "omnivore",
       ["huevo"], 120,
       ["tortilla_maiz","frijoles_negros"], 60,
       ["tomate","aguacate","pimiento_rojo","cebolla"], 80,
       ["aceite_oliva","queso_fresco","aguacate"], 12,
       "Huevos Divorciados con {carb}, {veg} y {fat}",
       "Plato mexicano con dos huevos en salsa verde y roja.",
       ["latam","us"], ["athletic_load"], [],
       ["maintain","muscle_gain"], ["lightly_active","moderately_active","very_active"],
       True, 10, 10, "México",
       ["Fríe los {prot}.","Calienta {carb}.","Acompaña con {veg}.","Termina con {fat}."],
       bucket="bf_omni"),
    _t("bfo_scrambled_bacon", ["north_american","european"], "breakfast", "omnivore",
       ["huevo","clara_huevo"], 130,
       ["pan_integral","tortilla_trigo","papa_blanca"], 50,
       ["espinaca","tomate","champinones","aguacate"], 70,
       ["bacon_pavo","queso_cheddar","aceite_oliva","mantequilla"], 12,
       "Huevos Revueltos con {fat}, {carb} y {veg}",
       "Huevos revueltos con bacon ligero y vegetales — desayuno americano clásico.",
       ["us","ca","eu","uk"], ["athletic_load"], ["hypertension"],
       ["maintain","muscle_gain"], ["lightly_active","moderately_active","very_active"],
       True, 5, 8, "USA",
       ["Bate {prot}.","Cocina los huevos revueltos.","Sirve con {carb}.","Acompaña con {veg}.","Termina con {fat}."],
       bucket="bf_omni"),
    _t("bfo_english_breakfast_light", ["european"], "breakfast", "omnivore",
       ["huevo","bacon_pavo","jamon_serrano"], 110,
       ["pan_integral","frijoles_rojos"], 60,
       ["tomate","champinones","espinaca"], 80,
       ["aceite_oliva","mantequilla"], 10,
       "Desayuno Inglés Light con {prot}, {carb} y {veg}",
       "Desayuno inglés ligero con bacon de pavo y vegetales asados.",
       ["uk","eu","us"], [], ["hypertension"],
       ["maintain","muscle_gain"], ["lightly_active","moderately_active","very_active"],
       False, 8, 12, "UK",
       ["Cocina {prot}.","Asa {veg}.","Calienta {carb}.","Termina con {fat}."],
       bucket="bf_omni"),
    _t("bfo_breakfast_bowl_quinoa", ["latam","north_american"], "breakfast", "omnivore",
       ["huevo","pollo_pechuga","pavo_pechuga","yogur_griego"], 110,
       ["quinoa","avena","camote"], 60,
       ["aguacate","espinaca","tomate","frutos_rojos","arandanos"], 80,
       ["almendras","nuez","semillas_chia","aceite_oliva"], 12,
       "Breakfast Bowl de {prot} con {carb}, {veg} y {fat}",
       "Bowl de desayuno fitness con proteína completa y quinoa.",
       ["us","ca","latam","eu"], ["athletic_load"], [],
       ["maintain","muscle_gain","weight_loss"], ["lightly_active","moderately_active","very_active"],
       True, 8, 10, "Fitness USA/Andes",
       ["Cocina {prot}.","Sirve sobre {carb}.","Añade {veg}.","Termina con {fat}."],
       bucket="bf_omni"),
    _t("bfo_chilaquiles_light", ["latam"], "breakfast", "omnivore",
       ["huevo","pollo_pechuga","pavo_pechuga"], 100,
       ["tortilla_maiz","frijoles_negros"], 50,
       ["tomate","aguacate","cebolla","pimiento_rojo"], 80,
       ["aceite_oliva","queso_fresco","aguacate"], 12,
       "Chilaquiles Light con {prot}, {veg} y {fat}",
       "Chilaquiles light con tortilla horneada y proteína magra.",
       ["latam","us"], [], ["hypertension"],
       ["maintain","muscle_gain"], ["lightly_active","moderately_active","very_active"],
       True, 10, 10, "México",
       ["Hornea {carb}.","Saltea con {veg}.","Añade {prot}.","Termina con {fat}."],
       bucket="bf_omni"),
    _t("bfo_tortilla_francesa_jamon", ["mediterranean","european"], "breakfast", "omnivore",
       ["huevo","jamon_serrano","queso_mozzarella"], 110,
       ["pan_integral","papa_blanca","tortilla_trigo"], 50,
       ["espinaca","tomate","champinones","esparragos"], 60,
       ["aceite_oliva","queso_parmesano","aguacate"], 10,
       "Tortilla Francesa con {prot}, {carb} y {veg}",
       "Tortilla francesa rellena con jamón y vegetales mediterráneos.",
       ["eu","us","latam"], ["athletic_load"], ["hypertension"],
       ["maintain","muscle_gain"], ["lightly_active","moderately_active","very_active"],
       True, 5, 6, "España/Francia",
       ["Bate {prot}.","Rellena con {fat} y {veg}.","Cocina como tortilla.","Sirve con {carb}."],
       bucket="bf_omni"),
    _t("bfo_waffles_proteicos", ["north_american"], "breakfast", "omnivore",
       ["huevo","yogur_griego","queso_cottage"], 100,
       ["avena","harina_avena"], 60,
       ["arandanos","frutos_rojos","platano_fruta","manzana"], 70,
       ["almendras","nuez","semillas_chia","miel_maple"], 12,
       "Waffles Proteicos con {carb}, {veg} y {fat}",
       "Waffles integrales proteicos con frutos rojos.",
       ["us","ca","eu","uk","latam"], ["athletic_load"], [],
       ["muscle_gain","maintain","weight_gain"], ["lightly_active","moderately_active","very_active"],
       True, 8, 10, "USA/Bélgica",
       ["Mezcla {prot} con {carb}.","Cocina en waflera.","Sirve con {veg}.","Termina con {fat}."],
       bucket="bf_omni"),
]

# ---------------------------------------------------------------------------
# Bucket B — CKD recommends +100. Strict gates: K≤400, P≤300, protein≤25, Na≤500.
# ---------------------------------------------------------------------------
CKD = [
    _t("ckd_lunch_chicken_white", ["asian","latam","mediterranean"], "lunch", "omnivore",
       ["pollo_pechuga","pavo_pechuga","clara_huevo","huevo"], 60,
       ["arroz_blanco","arroz_basmati","papa_blanca","polenta","fideos_arroz"], 100,
       ["pepino","repollo","judias_verdes","calabacin","lechuga"], 100,
       ["aceite_oliva","mantequilla"], 6,
       "Almuerzo Renal con {prot}, {carb} y {veg}",
       "Almuerzo renal con proteína controlada y vegetales bajos en potasio.",
       ["us","eu","latam","ca","uk"], ["ckd"], ["hypertension"],
       ["health","maintain"], ["sedentary","lightly_active"],
       True, 10, 15, "Renal-safe",
       ["Cocina {prot} sin sal.","Sirve sobre {carb}.","Acompaña con {veg} blanqueado.","Termina con {fat}."],
       bucket="ckd"),
    _t("ckd_dinner_white_fish", ["mediterranean","european"], "dinner", "pescatarian",
       ["bacalao","merluza","lenguado"], 80,
       ["arroz_blanco","papa_blanca","arroz_basmati","fideos_arroz","polenta"], 100,
       ["pepino","repollo","calabacin","judias_verdes","lechuga"], 100,
       ["aceite_oliva","mantequilla"], 6,
       "Cena Renal de {prot} con {carb} y {veg}",
       "Cena renal con pescado blanco bajo en fósforo y vegetales bajos K.",
       ["eu","us","uk"], ["ckd"], ["hypertension"],
       ["health","maintain"], ["sedentary","lightly_active"],
       False, 10, 18, "Mediterráneo renal",
       ["Hornea {prot} sin sal.","Acompaña con {carb}.","Sirve con {veg} blanqueado.","Termina con {fat}."],
       bucket="ckd"),
    _t("ckd_breakfast_egg_white", ["mediterranean","north_american"], "breakfast", "vegetarian",
       ["clara_huevo","huevo"], 80,
       ["arroz_blanco","polenta","fideos_arroz"], 60,
       ["pepino","calabacin","repollo","lechuga"], 80,
       ["aceite_oliva","mantequilla"], 6,
       "Desayuno Renal con {prot}, {carb} y {veg}",
       "Desayuno renal con claras y carbohidrato blanco bajo en K/P.",
       ["us","eu","uk","ca"], ["ckd"], ["hypertension"],
       ["health","maintain"], ["sedentary","lightly_active"],
       True, 8, 8, "USA/EU renal",
       ["Bate {prot}.","Cocina y sirve con {carb}.","Acompaña con {veg}.","Termina con {fat}."],
       bucket="ckd"),
    _t("ckd_snack_apple", ["north_american","european"], "snack", "vegetarian",
       ["clara_huevo","queso_cottage"], 50,
       ["arroz_blanco","fideos_arroz"], 25,
       ["manzana","pera","arandanos"], 70,
       ["mantequilla","aceite_oliva"], 5,
       "Snack Renal de {prot} con {veg} y {fat}",
       "Snack renal con frutas bajas en potasio.",
       ["us","eu","uk","ca"], ["ckd"], ["hypertension"],
       ["health","maintain"], ["sedentary","lightly_active"],
       True, 5, 0, "Renal-safe",
       ["Sirve {prot}.","Acompaña con {carb}.","Añade {veg} fresco.","Termina con {fat}."],
       bucket="ckd"),
    _t("ckd_dinner_chicken_pasta", ["mediterranean","european"], "dinner", "omnivore",
       ["pollo_pechuga","pavo_pechuga"], 60,
       ["pasta_blanca","arroz_blanco","fideos_arroz","papa_blanca"], 100,
       ["pepino","calabacin","judias_verdes","repollo","lechuga"], 100,
       ["aceite_oliva","mantequilla"], 6,
       "Cena Renal de {prot} con {carb} y {veg}",
       "Cena renal con pollo y pasta blanca controlada en K/P.",
       ["us","eu","uk"], ["ckd"], ["hypertension"],
       ["health","maintain"], ["sedentary","lightly_active"],
       True, 10, 15, "Mediterráneo renal",
       ["Cocina {prot} sin sal.","Hierve {carb}.","Acompaña con {veg}.","Termina con {fat}."],
       bucket="ckd"),
]

# ---------------------------------------------------------------------------
# Bucket C — Lactation +200. pregnancy_safe + folate≥150 + Ca≥300 + Fe≥4, kcal 450-700.
# ALL ingredient pools must be lactation-safe (cooked salmon OK, no soft cheese,
# no raw fish, no liver, no alcohol, no raw egg).
# ---------------------------------------------------------------------------
LACTATION = [
    _t("lact_salmon_bowl", ["mediterranean","north_american"], "lunch", "pescatarian",
       ["salmon"], 120,
       ["quinoa","arroz_integral","camote"], 100,
       ["espinaca","brocoli","kale","esparragos","aguacate"], 130,
       ["aceite_oliva","almendras","semillas_chia","nuez"], 15,
       "Bowl de Lactancia con {prot}, {carb} y {veg}",
       "Bowl para lactancia con salmón omega-3, folato y calcio.",
       ["us","eu","uk","ca","latam"], ["lactation","iron_deficiency_anemia"], [],
       ["maintain","health","muscle_gain"], ["lightly_active","moderately_active"],
       True, 12, 18, "Mediterráneo",
       ["Hornea {prot} hasta cocción completa.","Sirve sobre {carb}.","Acompaña con {veg}.","Termina con {fat}."],
       bucket="lactation"),
    _t("lact_lentil_stew", ["latam","mediterranean"], "lunch", "omnivore",
       ["lentejas","pollo_pechuga","pavo_pechuga"], 150,
       ["arroz_integral","quinoa","camote"], 80,
       ["espinaca","kale","zanahoria","tomate","brocoli"], 130,
       ["aceite_oliva","aguacate","almendras","semillas_lino"], 15,
       "Guiso de Lactancia con {prot}, {carb} y {veg}",
       "Guiso para lactancia con lentejas, hierro y folato.",
       ["us","eu","latam","ca"], ["lactation","iron_deficiency_anemia"], [],
       ["maintain","health"], ["lightly_active","moderately_active"],
       True, 12, 25, "Latam/Med",
       ["Cocina {prot} con {veg}.","Sirve con {carb}.","Termina con {fat}."],
       bucket="lactation"),
    _t("lact_oat_breakfast", ["north_american","mediterranean"], "breakfast", "vegetarian",
       ["yogur_griego","queso_cottage","huevo"], 150,
       ["avena_seca","harina_avena","quinoa"], 70,
       ["frutos_rojos","arandanos","espinaca","platano_fruta"], 100,
       ["almendras","nuez","semillas_chia","semillas_lino"], 18,
       "Desayuno de Lactancia con {prot}, {carb} y {veg}",
       "Desayuno galactogogo con avena, semillas y lácteo pasteurizado.",
       ["us","eu","uk","ca","latam"], ["lactation","iron_deficiency_anemia"], [],
       ["maintain","health","muscle_gain"], ["lightly_active","moderately_active"],
       True, 8, 8, "USA wellness",
       ["Cocina {carb} con leche.","Sirve con {prot}.","Acompaña con {veg}.","Termina con {fat}."],
       bucket="lactation"),
    _t("lact_chicken_quinoa", ["latam","mediterranean"], "dinner", "omnivore",
       ["pollo_pechuga","pavo_pechuga"], 130,
       ["quinoa","arroz_integral","camote","lentejas"], 90,
       ["espinaca","brocoli","kale","zanahoria","esparragos"], 130,
       ["aceite_oliva","aguacate","almendras","semillas_chia"], 15,
       "Cena de Lactancia con {prot}, {carb} y {veg}",
       "Cena para lactancia con pollo cocido, quinoa y vegetales ricos en folato.",
       ["us","eu","latam","ca"], ["lactation","iron_deficiency_anemia"], [],
       ["maintain","health","muscle_gain"], ["lightly_active","moderately_active"],
       True, 12, 22, "Mediterráneo/Andes",
       ["Cocina {prot} completamente.","Sirve con {carb}.","Acompaña con {veg}.","Termina con {fat}."],
       bucket="lactation"),
    _t("lact_frittata_spinach", ["mediterranean","european"], "lunch", "vegetarian",
       ["huevo","queso_mozzarella","queso_cottage"], 150,
       ["quinoa","papa_blanca","camote"], 80,
       ["espinaca","brocoli","kale","esparragos","champinones"], 130,
       ["aceite_oliva","queso_parmesano","almendras"], 15,
       "Frittata de Lactancia con {prot}, {veg} y {carb}",
       "Frittata para lactancia con espinaca rica en folato, huevo y queso pasteurizado.",
       ["us","eu","latam"], ["lactation","iron_deficiency_anemia"], [],
       ["maintain","health"], ["lightly_active","moderately_active"],
       True, 10, 18, "Italia",
       ["Bate {prot}.","Saltea {veg}.","Hornea como frittata.","Sirve con {carb}.","Termina con {fat}."],
       bucket="lactation"),
    _t("lact_salmon_pasta", ["mediterranean","north_american"], "dinner", "pescatarian",
       ["salmon"], 120,
       ["pasta_integral","quinoa","arroz_integral"], 90,
       ["espinaca","brocoli","kale","esparragos","tomate"], 120,
       ["queso_parmesano","queso_mozzarella","almendras"], 25,
       "Pasta de Lactancia con {prot}, {veg} y {carb}",
       "Pasta integral con salmón cocido, omega-3 y folato.",
       ["us","eu","uk","ca"], ["lactation"], [],
       ["maintain","muscle_gain","health"], ["lightly_active","moderately_active"],
       True, 10, 18, "Italia/Mediterráneo",
       ["Cocina {carb}.","Hornea {prot} completamente.","Saltea {veg}.","Mezcla y termina con {fat}."],
       bucket="lactation"),
    # High-Ca template: dairy in prot, leafy veg ensures folate.
    _t("lact_yogurt_oats", ["north_american","mediterranean"], "breakfast", "vegetarian",
       ["yogur_griego","queso_cottage"], 180,
       ["avena_seca","harina_avena","quinoa"], 70,
       ["espinaca","kale","frutos_rojos","arandanos"], 110,
       ["almendras","semillas_chia","semillas_lino","nuez"], 20,
       "Yogur Lactancia con {carb}, {veg} y {fat}",
       "Bowl de yogur griego con avena, semillas y folato verde.",
       ["us","ca","eu","uk","latam"], ["lactation","iron_deficiency_anemia"], [],
       ["maintain","muscle_gain","health"], ["lightly_active","moderately_active"],
       True, 8, 0, "USA/Med",
       ["Sirve {prot}.","Mezcla con {carb}.","Añade {veg}.","Termina con {fat}."],
       bucket="lactation"),
    # High-Ca + Fe template via cheese + legumes
    _t("lact_chickpea_cheese_bowl", ["mediterranean","middle_eastern"], "lunch", "vegetarian",
       ["garbanzos","lentejas","edamame"], 180,
       ["quinoa","arroz_integral","camote"], 90,
       ["espinaca","kale","brocoli","esparragos","tomate"], 130,
       ["queso_mozzarella","queso_parmesano","almendras","aceite_oliva"], 22,
       "Bowl Mediterráneo Lactancia con {prot}, {carb} y {veg}",
       "Bowl mediterráneo con legumbres ricas en folato/hierro y queso pasteurizado por calcio.",
       ["us","eu","uk","latam"], ["lactation","iron_deficiency_anemia"], [],
       ["maintain","health"], ["lightly_active","moderately_active"],
       True, 12, 18, "Mediterráneo",
       ["Cocina {prot}.","Sirve con {carb}.","Acompaña con {veg}.","Termina con {fat}."],
       bucket="lactation"),
    # Forced calcium via mozzarella/parmesano in fat slot for omnivore dinners
    _t("lact_chicken_cheese_quinoa", ["latam","mediterranean"], "dinner", "omnivore",
       ["pollo_pechuga","pavo_pechuga","carne_magra_res"], 130,
       ["quinoa","arroz_integral","camote"], 80,
       ["espinaca","kale","brocoli","esparragos"], 130,
       ["queso_mozzarella","queso_parmesano","almendras","queso_cheddar"], 25,
       "Cena Lactancia con {prot}, {carb} y {fat}",
       "Cena lactancia con pollo, queso pasteurizado por calcio y leafy greens.",
       ["us","eu","latam","ca"], ["lactation","iron_deficiency_anemia"], [],
       ["maintain","muscle_gain","health"], ["lightly_active","moderately_active"],
       True, 12, 22, "Mediterráneo",
       ["Cocina {prot} completamente.","Sirve con {carb}.","Acompaña con {veg}.","Termina con {fat}."],
       bucket="lactation"),
]

# ---------------------------------------------------------------------------
# Bucket D — Weight_gain dinners +200. Gates: kcal 700-1200, protein≥35, carbs≥70.
# ---------------------------------------------------------------------------
WG_DINNER = [
    _t("wg_pasta_carbonara", ["mediterranean","european"], "dinner", "omnivore",
       ["pollo_pechuga","pavo_pechuga","jamon_serrano","bacon_pavo"], 150,
       ["pasta_integral","pasta_blanca"], 250,
       ["champinones","espinaca","brocoli","cebolla"], 80,
       ["queso_parmesano","aceite_oliva","mantequilla","queso_mozzarella"], 25,
       "Carbonara de {prot} con {carb}, {veg} y {fat}",
       "Pasta carbonara con pollo y queso parmesano para volumen calórico.",
       ["us","eu","uk","latam"], ["athletic_load"], ["hypertension"],
       ["muscle_gain","weight_gain"], ["very_active","extra_active","moderately_active"],
       True, 12, 18, "Italia",
       ["Cocina {carb}.","Saltea {prot}.","Mezcla con huevo y {fat}.","Acompaña con {veg}."],
       bucket="wg_dinner"),
    _t("wg_arroz_frito_mixto", ["asian"], "dinner", "omnivore",
       ["pollo_pechuga","camaron","huevo","carne_magra_res"], 160,
       ["arroz_blanco","arroz_basmati","fideos_arroz"], 180,
       ["brocoli","pimiento_rojo","cebolla","zanahoria","champinones"], 100,
       ["aceite_oliva","almendras","nuez"], 20,
       "Arroz Frito con {prot}, {carb}, {veg} y {fat}",
       "Arroz frito estilo asiático con proteína mixta para volumen calórico.",
       ["us","eu","uk","ca","latam"], ["athletic_load"], ["hypertension"],
       ["muscle_gain","weight_gain"], ["very_active","extra_active","moderately_active"],
       True, 10, 15, "China",
       ["Cocina {prot}.","Saltea {carb} con {veg}.","Mezcla.","Termina con {fat}."],
       bucket="wg_dinner"),
    _t("wg_lasagna_bolognesa", ["mediterranean","european"], "dinner", "omnivore",
       ["carne_molida_res","pavo_pechuga","pollo_pechuga"], 160,
       ["pasta_integral","pasta_blanca"], 220,
       ["tomate","espinaca","champinones","cebolla","pimiento_rojo"], 100,
       ["queso_mozzarella","queso_parmesano","aceite_oliva"], 25,
       "Lasagna de {prot} con {carb}, {veg} y {fat}",
       "Lasagna italiana con carne magra y queso fundido — densidad calórica alta.",
       ["us","eu","uk","ca","latam"], ["athletic_load"], ["hypertension"],
       ["muscle_gain","weight_gain"], ["very_active","extra_active","moderately_active"],
       True, 20, 35, "Italia",
       ["Cocina {prot} con {veg}.","Capas con {carb}.","Cubre con {fat}.","Hornea."],
       bucket="wg_dinner"),
    _t("wg_rice_chicken_avocado", ["latam","north_american"], "dinner", "omnivore",
       ["pollo_pechuga","pavo_pechuga","carne_magra_res","huevo"], 170,
       ["arroz_blanco","arroz_integral","arroz_basmati","quinoa"], 180,
       ["aguacate","tomate","espinaca","frijoles_negros","pimiento_rojo"], 100,
       ["aceite_oliva","aguacate","queso_cheddar","almendras"], 22,
       "Bowl Bulking con {prot}, {carb}, {veg} y {fat}",
       "Bowl alto en kcal con arroz, proteína magra y aguacate.",
       ["us","ca","latam"], ["athletic_load"], [],
       ["muscle_gain","weight_gain"], ["very_active","extra_active","moderately_active"],
       True, 10, 18, "USA/Latam fitness",
       ["Cocina {prot}.","Sirve sobre {carb}.","Acompaña con {veg}.","Termina con {fat}."],
       bucket="wg_dinner"),
    _t("wg_shepherds_pie", ["european"], "dinner", "omnivore",
       ["carne_molida_res","cordero","pavo_pechuga"], 170,
       ["papa_blanca","camote","arroz_integral"], 280,
       ["zanahoria","cebolla","champinones","tomate","brocoli"], 100,
       ["queso_cheddar","mantequilla","aceite_oliva","queso_parmesano"], 22,
       "Shepherd's Pie de {prot} con {carb}, {veg} y {fat}",
       "Shepherd's pie británico clásico — denso en kcal.",
       ["uk","eu","us","ca"], ["athletic_load"], ["hypertension"],
       ["muscle_gain","weight_gain"], ["very_active","extra_active","moderately_active"],
       True, 15, 30, "UK",
       ["Cocina {prot} con {veg}.","Cubre con puré de {carb}.","Gratina con {fat}."],
       bucket="wg_dinner"),
    _t("wg_paella_mixta", ["mediterranean","european"], "dinner", "omnivore",
       ["pollo_pechuga","camaron","jamon_serrano"], 160,
       ["arroz_blanco","arroz_basmati"], 200,
       ["pimiento_rojo","tomate","cebolla","esparragos","judias_verdes"], 100,
       ["aceite_oliva","almendras","queso_parmesano"], 20,
       "Paella Mixta con {prot}, {carb}, {veg} y {fat}",
       "Paella española mixta — densidad calórica alta y proteína completa.",
       ["eu","us","uk","latam"], ["athletic_load"], ["hypertension"],
       ["muscle_gain","weight_gain"], ["very_active","extra_active","moderately_active"],
       False, 15, 30, "España",
       ["Sofríe {veg}.","Añade {prot} y {carb}.","Cocina con caldo.","Termina con {fat}."],
       bucket="wg_dinner"),
    _t("wg_burrito_bowl", ["latam","north_american"], "dinner", "omnivore",
       ["pollo_pechuga","carne_molida_res","pavo_pechuga"], 170,
       ["arroz_blanco","arroz_integral","quinoa","frijoles_negros"], 200,
       ["aguacate","tomate","pimiento_rojo","espinaca","cebolla"], 100,
       ["queso_cheddar","queso_mozzarella","aceite_oliva","aguacate"], 22,
       "Burrito Bowl Bulking de {prot} con {carb}, {veg} y {fat}",
       "Burrito bowl tex-mex bulking con proteína magra y arroz.",
       ["us","ca","latam"], ["athletic_load"], [],
       ["muscle_gain","weight_gain"], ["very_active","extra_active","moderately_active"],
       True, 12, 18, "TexMex",
       ["Cocina {prot}.","Sirve sobre {carb}.","Añade {veg}.","Termina con {fat}."],
       bucket="wg_dinner"),
    _t("wg_pasta_bolognesa", ["mediterranean","european"], "dinner", "omnivore",
       ["carne_molida_res","pavo_pechuga","pollo_pechuga"], 160,
       ["pasta_integral","pasta_blanca"], 180,
       ["salsa_tomate","cebolla","champinones","espinaca","zanahoria"], 110,
       ["queso_parmesano","aceite_oliva","queso_mozzarella"], 22,
       "Pasta Boloñesa de {prot} con {carb}, {veg} y {fat}",
       "Pasta boloñesa clásica con proteína magra y densidad calórica.",
       ["eu","us","uk","latam"], ["athletic_load"], ["hypertension"],
       ["muscle_gain","weight_gain"], ["very_active","extra_active","moderately_active"],
       True, 12, 25, "Italia",
       ["Cocina {prot} con {veg}.","Hierve {carb}.","Mezcla.","Termina con {fat}."],
       bucket="wg_dinner"),
    _t("wg_salmon_rice_bowl", ["asian","mediterranean"], "dinner", "pescatarian",
       ["salmon","atun_lata_agua","camaron"], 160,
       ["arroz_blanco","arroz_basmati","arroz_integral","quinoa"], 200,
       ["espinaca","brocoli","aguacate","pimiento_rojo","esparragos"], 100,
       ["aceite_oliva","almendras","semillas_chia","aguacate"], 22,
       "Bowl Bulking de {prot} con {carb}, {veg} y {fat}",
       "Bowl pescatariano bulking alto en omega-3 y carbohidratos densos.",
       ["us","eu","uk","ca","latam"], ["athletic_load","dyslipidemia"], [],
       ["muscle_gain","weight_gain"], ["very_active","extra_active","moderately_active"],
       True, 10, 18, "Asia/Med fitness",
       ["Cocina {prot}.","Sirve sobre {carb}.","Acompaña con {veg}.","Termina con {fat}."],
       bucket="wg_dinner"),
]

# ---------------------------------------------------------------------------
# Aggregate.
# ---------------------------------------------------------------------------
def _fanout(templates: list[dict]) -> list[dict]:
    out: list[dict] = []
    for tpl in templates:
        cuisines = tpl["cuisine"]
        if len(cuisines) <= 1:
            out.append(tpl)
            continue
        for i, c in enumerate(cuisines):
            clone = dict(tpl)
            rotated = [c] + [x for x in cuisines if x != c]
            clone["cuisine"] = rotated
            clone["tid"] = f"{tpl['tid']}_c{i}"
            out.append(clone)
    return out


ALL_TEMPLATES = _fanout(BREAKFAST_OMNI + CKD + LACTATION + WG_DINNER)

BUCKET_CAPS = {"bf_omni": 500, "ckd": 100, "lactation": 200, "wg_dinner": 200, "generic": 0}

# ---------------------------------------------------------------------------
# Pregnancy-unsafe ingredient tokens. Used for lactation hard reject AND
# global pregnancy_safe audit. Word-boundary, case-insensitive, EN+ES.
# Excludes ambiguous tokens (e.g. feta, plain "wine" in small cooking amounts).
# ---------------------------------------------------------------------------
PREGNANCY_UNSAFE_TOKENS = [
    # Raw fish / sushi
    "sushi", "sashimi", "tartar", "tartare", "crudo", "cruda",
    "ceviche", "carpaccio", "poke", "raw fish",
    "pescado crudo", r"salm[oó]n crudo", r"at[uú]n crudo",
    # Soft / unpasteurized cheese
    "brie", "camembert", "roquefort", "gorgonzola", "blue cheese", "queso azul",
    "queso fresco artesanal",
    # High-mercury fish
    "shark", r"tibur[oó]n", "swordfish", "pez espada", "king mackerel",
    "tilefish", "marlin", "bigeye tuna", r"at[uú]n rojo", "bluefin tuna",
    # Liver / organ
    "liver", r"h[ií]gado", r"pat[eé] de h[ií]gado", "foie gras",
    r"ri[ñn][oó]n", "kidney", "sweetbread", "mollejas",
    # Alcohol (strong)
    "whisky", "whiskey", "rum", "vodka", "tequila", "vino tinto",
    "licor", "brandy", "champagne", "champa[ñn]a",
    # Raw eggs
    "raw egg", "huevo crudo", "mayonesa casera", "homemade mayo", r"tiramis[uú]",
]

PREGNANCY_REGEX = re.compile(
    r"(?<![\w])(?:" + "|".join(PREGNANCY_UNSAFE_TOKENS) + r")(?![\w])",
    re.IGNORECASE,
)


def pregnancy_unsafe_reason(ingredients_text: str) -> str | None:
    m = PREGNANCY_REGEX.search(ingredients_text)
    return m.group(0).lower() if m else None


# ---------------------------------------------------------------------------
# Dedup signature.
# ---------------------------------------------------------------------------
_STOPWORDS = {
    "g","ml","gr","de","y","con","sin","la","el","las","los","una","un",
    "fresco","fresca","frescos","frescas","cocido","cocida","picado","picada",
    "rebanado","rallado","molido","crudo","cruda","entero","entera",
    "rojo","roja","verde","blanco","blanca","negro","negra","amarillo",
    "grande","pequeno","pequeña","mediano","mediana",
    "al","gusto","sal","pimienta","especias","aceite","oliva","virgen",
    "extra","integral","light","azucar","azúcar","baja","sodio",
    "cucharada","cucharadita","taza","tazas","unidad","unidades",
    "ramita","hoja","hojas","diente","dientes","pizca",
}


def _extract_core_nouns(ing_str: str) -> str:
    s = ing_str.lower()
    s = re.sub(r"[0-9]+([.,][0-9]+)?", " ", s)
    s = re.sub(r"[^\w\sáéíóúñ]", " ", s)
    tokens = [t for t in s.split() if t and t not in _STOPWORDS and len(t) > 2]
    seen: list[str] = []
    for t in tokens:
        if t not in seen:
            seen.append(t)
        if len(seen) >= 3:
            break
    return "_".join(seen)


def _signature(recipe: dict) -> str:
    name_norm = re.sub(r"\s+", " ", recipe["name"].lower().strip())
    name_norm = re.sub(r"[^\w\sáéíóúñ]", "", name_norm)
    ings = sorted(_extract_core_nouns(i) for i in recipe["execution"]["ingredients"] if _extract_core_nouns(i))
    return hashlib.sha1(f"{name_norm}|{','.join(ings)}".encode()).hexdigest()


def detect_allergens(component_keys: list[str]) -> list[str]:
    found: set[str] = set()
    for k in component_keys:
        for a in ALLERGEN_FROM_KEY.get(k, ()):
            found.add(a)
    return sorted(found)


def macros_from_components(components: list[tuple[str, float]]) -> dict:
    p = c = f = fib = sug = na = satfat = k_mg = ph_mg = fol = ca = fe = 0.0
    gi_weighted = gi_carb_total = 0.0
    for key, grams in components:
        ing = ING[key]
        factor = grams / 100.0
        p += ing["p"] * factor
        c += ing["c"] * factor
        f += ing["f"] * factor
        fib += ing["fib"] * factor
        sug += ing["sug"] * factor
        na += ing["na"] * factor
        satfat += ing.get("satfat", 0.0) * factor
        k_mg += ing.get("k", 0) * factor
        ph_mg += ing.get("ph", 0) * factor
        fol += ing.get("fol", 0) * factor
        ca += ing.get("ca", 0) * factor
        fe += ing.get("fe", 0) * factor
        carb_contrib = ing["c"] * factor
        gi_weighted += ing["gi"] * carb_contrib
        gi_carb_total += carb_contrib
    gi = int(round(gi_weighted / gi_carb_total)) if gi_carb_total > 0 else None
    p_i = int(round(p)); c_i = int(round(c)); f_i = int(round(f))
    kcal = 4 * p_i + 4 * c_i + 9 * f_i
    gl = (gi * c_i / 100.0) if gi is not None else None
    return {
        "calories": kcal, "protein_g": p_i, "carbs_g": c_i, "fat_g": f_i,
        "fiber_g": int(round(fib)), "sugar_g": int(round(sug)),
        "sodium_mg": int(round(na)), "gi": gi,
        "gl": round(gl, 1) if gl is not None else None,
        "satfat_g": int(round(satfat)),
        "potassium_mg": int(round(k_mg)), "phosphorus_mg": int(round(ph_mg)),
        "folate_ug": int(round(fol)), "calcium_mg": int(round(ca)),
        "iron_mg": round(fe, 1),
    }


def deterministic_id(template_id: str, slots: tuple[str, ...]) -> str:
    h = hashlib.sha1(("|".join(("round2", template_id, *slots))).encode()).hexdigest()
    return f"nova_meal_r2_{h[:10]}"


def validate_base(recipe: dict) -> tuple[bool, str]:
    mc = recipe["matching_criteria"]
    np_ = recipe["nutrition_profile"]
    m = np_["macros"]
    kcal = np_["calories"]
    if kcal <= 0:
        return False, "kcal<=0"
    derived = 4 * m["protein_g"] + 4 * m["carbs_g"] + 9 * m["fat_g"]
    if abs(derived - kcal) / kcal > 0.05:
        return False, f"macro_drift={abs(derived-kcal)/kcal:.3f}"
    if not (100 <= kcal <= 1500):
        return False, f"kcal_out_of_range={kcal}"
    if not (0 <= m["protein_g"] <= 80):
        return False, "protein_out_of_range"
    if not (0 <= m["carbs_g"] <= 200):
        return False, "carbs_out_of_range"
    if not (0 <= m["fat_g"] <= 80):
        return False, "fat_out_of_range"
    for v in mc["allergens"]:
        if v not in ALLERGENS_14: return False, f"allergen_drift={v}"
    for v in mc["recommended_for_conditions"]:
        if v not in CONDITIONS_25: return False, f"rec_cond_drift={v}"
    for v in mc["contraindicated_conditions"]:
        if v not in CONDITIONS_25: return False, f"contra_cond_drift={v}"
    for v in mc["target_goals"]:
        if v not in GOALS_5: return False, f"goal_drift={v}"
    for v in mc["suitable_for_activity"]:
        if v not in ACTIVITY_LEVELS_5: return False, f"activity_drift={v}"
    for v in mc["regions"]:
        if v not in REGIONS_5: return False, f"region_drift={v}"
    if not mc["regions"]:
        return False, "regions_empty"
    if recipe["execution"]["meal_time"] not in MEAL_TIMES_4:
        return False, "meal_time_drift"
    return True, "ok"


def bucket_gate(recipe: dict, bucket: str) -> tuple[bool, str]:
    m = recipe["nutrition_profile"]["macros"]
    kcal = recipe["nutrition_profile"]["calories"]
    micros = recipe["nutrition_profile"]["micronutrients"]
    rec = recipe["matching_criteria"]["recommended_for_conditions"]
    ingredients_text = " ".join(recipe["execution"]["ingredients"]).lower()
    preg_safe = recipe["matching_criteria"].get("pregnancy_safe", False)

    if bucket == "ckd":
        if m["protein_g"] > 25: return False, "ckd_protein_high"
        if m["sodium_mg"] > 500: return False, "ckd_sodium_high"
        if micros["potassium_mg"] is not None and micros["potassium_mg"] > 400:
            return False, "ckd_potassium_high"
        if micros["phosphorus_mg"] is not None and micros["phosphorus_mg"] > 300:
            return False, "ckd_phosphorus_high"
        if "ckd" not in rec: return False, "ckd_missing_recommend"
    elif bucket == "lactation":
        if "lactation" not in rec: return False, "lact_missing_recommend"
        if not preg_safe: return False, "lact_not_preg_safe"
        unsafe = pregnancy_unsafe_reason(ingredients_text)
        if unsafe: return False, f"lact_unsafe_token={unsafe}"
        if micros.get("folate_ug") is None or micros["folate_ug"] < 150:
            return False, f"lact_folate_low={micros.get('folate_ug')}"
        if micros.get("calcium_mg") is None or micros["calcium_mg"] < 300:
            return False, f"lact_calcium_low={micros.get('calcium_mg')}"
        if micros.get("iron_mg") is None or micros["iron_mg"] < 4:
            return False, f"lact_iron_low={micros.get('iron_mg')}"
        if not (450 <= kcal <= 700):
            return False, f"lact_kcal_out={kcal}"
    elif bucket == "wg_dinner":
        if not (700 <= kcal <= 1200):
            return False, f"wg_kcal_out={kcal}"
        if m["protein_g"] < 35: return False, f"wg_protein_low={m['protein_g']}"
        if m["carbs_g"] < 70: return False, f"wg_carbs_low={m['carbs_g']}"
        goals = recipe["matching_criteria"]["target_goals"]
        if not ({"weight_gain","muscle_gain"} & set(goals)):
            return False, "wg_missing_goal"
    elif bucket == "bf_omni":
        if recipe["execution"]["meal_time"] != "breakfast":
            return False, "bf_wrong_meal_time"
    return True, "ok"


def build_one(tpl: dict, prot: str, carb: str, veg: str, fat: str) -> dict:
    components = [
        (prot, tpl["prot_g"]),
        (carb, tpl["carb_g"]),
        (veg, tpl["veg_g"]),
        (fat, tpl["fat_g"]),
    ]
    m = macros_from_components(components)
    allergens = detect_allergens([prot, carb, veg, fat])
    cuisine_label = {
        "north_american": "USA", "mediterranean": "Med", "latam": "LatAm",
        "asian": "Asia", "middle_eastern": "ME", "european": "EU",
        "fusion": "Fusion", "nordic": "Nordic", "eu": "EU",
    }
    cuisine_tag = cuisine_label.get(tpl["cuisine"][0], tpl["cuisine"][0][:6].title())
    base_name = tpl["name"].format(
        prot=DISPLAY[prot], carb=DISPLAY[carb], veg=DISPLAY[veg], fat=DISPLAY[fat],
    )
    base_lower = base_name.lower()
    missing_tags: list[str] = []
    for label, _key in ((DISPLAY[prot], "prot"), (DISPLAY[carb], "carb"),
                       (DISPLAY[veg], "veg"), (DISPLAY[fat], "fat")):
        if label.lower() not in base_lower:
            missing_tags.append(label)
    suffix_extra = (" + " + ", ".join(missing_tags)) if missing_tags else ""
    name = f"{base_name}{suffix_extra} ({cuisine_tag} · {tpl['tid'][-6:]})"
    desc = tpl["desc"]
    instructions = [s.format(prot=DISPLAY[prot], carb=DISPLAY[carb],
                              veg=DISPLAY[veg], fat=DISPLAY[fat])
                    for s in tpl["instructions"]]
    ingredients = [
        f"{tpl['prot_g']} g de {DISPLAY[prot]}",
        f"{tpl['carb_g']} g de {DISPLAY[carb]}",
        f"{tpl['veg_g']} g de {DISPLAY[veg]}",
        f"{tpl['fat_g']} g de {DISPLAY[fat]}",
        "Sal, pimienta y especias al gusto",
    ]
    rid = deterministic_id(tpl["tid"], (prot, carb, veg, fat))

    rec = list(tpl["rec"])
    contra = list(tpl["contra"])
    bucket = tpl.get("bucket", "generic")

    micronutrients: dict = {
        "gi": m["gi"], "gl": m["gl"],
        "potassium_mg": None, "phosphorus_mg": None, "iron_mg": None,
        "heme_pct": None, "calcium_mg": None, "omega3_mg": None, "folate_ug": None,
    }
    if bucket == "ckd":
        micronutrients["potassium_mg"] = m["potassium_mg"]
        micronutrients["phosphorus_mg"] = m["phosphorus_mg"]
    if bucket == "lactation":
        micronutrients["folate_ug"] = m["folate_ug"]
        micronutrients["calcium_mg"] = m["calcium_mg"]
        micronutrients["iron_mg"] = m["iron_mg"]

    derived_kcal = 4 * m["protein_g"] + 4 * m["carbs_g"] + 9 * m["fat_g"]
    consistency_pct = round(abs(derived_kcal - m["calories"]) / max(m["calories"], 1) * 100, 2)

    return {
        "id": rid,
        "name": name,
        "description": desc,
        "image_url": PLACEHOLDER_IMG,
        "nutrition_profile": {
            "calories": m["calories"],
            "macros": {
                "protein_g": m["protein_g"], "carbs_g": m["carbs_g"], "fat_g": m["fat_g"],
                "fiber_g": m["fiber_g"], "sugar_g": m["sugar_g"],
                "sat_fat_g": m["satfat_g"], "sodium_mg": m["sodium_mg"],
            },
            "micronutrients": micronutrients,
        },
        "matching_criteria": {
            "target_goals": list(tpl["goals"]),
            "suitable_for_activity": list(tpl["act"]),
            "recommended_for_conditions": rec,
            "contraindicated_conditions": contra,
            "allergens": allergens,
            "regions": list(tpl["regions"]),
            "dietary_pattern": tpl["diet"],
            "cuisine_region": list(tpl["cuisine"]),
            "meal_format": "solid",
            "pregnancy_safe": bool(tpl["preg"]),
        },
        "execution": {
            "meal_time": tpl["meal_time"],
            "prep_time_minutes": tpl["prep"],
            "cook_time_minutes": tpl["cook"],
            "image_url": None,
            "ingredients": ingredients,
            "instructions": instructions,
            "servings": 1,
            "source_catalog": SOURCE_CATALOG,
        },
        "audit": {
            "schema_version": "v2",
            "macro_consistency_pct": consistency_pct,
            "gl_estimated": m["gl"],
            "cultural_origin": tpl.get("origin"),
            "image_status": "placeholder_pending_upload",
            "generated_at": "2026-06-01",
            "bucket": bucket,
        },
    }


def main() -> None:
    print("Loading existing catalog for dedup index...")
    existing = json.loads(EXISTING_CATALOG.read_text())
    existing_ids: set[str] = {r["id"] for r in existing if "id" in r}
    existing_sigs: set[str] = set()
    cell_names: dict[tuple, list[str]] = {}
    for r in existing:
        try:
            existing_sigs.add(_signature(r))
        except Exception:
            pass
        mc = r.get("matching_criteria", {})
        ex = r.get("execution", {})
        cuisine = mc.get("cuisine_region") or [""]
        key = (ex.get("meal_time", ""), mc.get("dietary_pattern", ""),
               cuisine[0] if cuisine else "")
        cell_names.setdefault(key, []).append(r.get("name", "").lower())
    print(f"Existing: ids={len(existing_ids)} sigs={len(existing_sigs)} cells={len(cell_names)}")

    out: list[dict] = []
    new_sigs: set[str] = set()
    new_ids: set[str] = set()
    cell_names_exact: dict[tuple, set[str]] = {}
    rejection_counts: dict[str, int] = {}
    rejection_samples: list[tuple[str, str]] = []
    bucket_counts: dict[str, int] = {}
    bucket_accepted: dict[str, int] = {}
    bucket_rejected: dict[str, int] = {}
    total_attempts = 0

    def reject(rid: str, reason: str, bucket: str) -> None:
        key = reason.split("=", 1)[0]
        rejection_counts[key] = rejection_counts.get(key, 0) + 1
        bucket_rejected[bucket] = bucket_rejected.get(bucket, 0) + 1
        if len(rejection_samples) < 200:
            rejection_samples.append((rid, f"{bucket}:{reason}"))

    for tpl in ALL_TEMPLATES:
        bucket = tpl.get("bucket", "generic")
        cap = BUCKET_CAPS.get(bucket, 0)
        for prot, carb, veg, fat in product(tpl["prot_pool"], tpl["carb_pool"],
                                             tpl["veg_pool"], tpl["fat_pool"]):
            if bucket_counts.get(bucket, 0) >= cap:
                break
            total_attempts += 1
            try:
                recipe = build_one(tpl, prot, carb, veg, fat)
            except Exception as exc:  # noqa: BLE001
                reject("?", f"build_error={exc.__class__.__name__}", bucket)
                continue
            rid = recipe["id"]
            if rid in existing_ids or rid in new_ids:
                reject(rid, "duplicate_id", bucket)
                continue
            ok, reason = validate_base(recipe)
            if not ok:
                reject(rid, reason, bucket)
                continue
            ok, reason = bucket_gate(recipe, bucket)
            if not ok:
                reject(rid, reason, bucket)
                continue
            sig = _signature(recipe)
            if sig in existing_sigs or sig in new_sigs:
                reject(rid, "signature_collision", bucket)
                continue
            mc = recipe["matching_criteria"]
            ex = recipe["execution"]
            cuisine = mc["cuisine_region"]
            cell_key = (ex["meal_time"], mc["dietary_pattern"],
                        cuisine[0] if cuisine else "")
            name_lower = recipe["name"].lower()
            cell_set = cell_names_exact.get(cell_key)
            if cell_set is None:
                cell_set = set(n.lower() for n in cell_names.get(cell_key, []))
                cell_names_exact[cell_key] = cell_set
            if name_lower in cell_set:
                reject(rid, "name_exact_collision", bucket)
                continue
            new_ids.add(rid)
            new_sigs.add(sig)
            cell_set.add(name_lower)
            out.append(recipe)
            bucket_counts[bucket] = bucket_counts.get(bucket, 0) + 1
            bucket_accepted[bucket] = bucket_accepted.get(bucket, 0) + 1

    OUT.write_text(json.dumps(out, ensure_ascii=False))
    summary_lines = [
        "Round2 batch generation summary",
        f"templates={len(ALL_TEMPLATES)}",
        f"attempts={total_attempts}",
        f"accepted={len(out)}",
        f"rejected_total={total_attempts - len(out)}",
        "",
        "Per-bucket accepted:",
    ]
    for b in sorted(bucket_accepted):
        summary_lines.append(f"  {b}: accepted={bucket_accepted[b]} rejected={bucket_rejected.get(b,0)}")
    summary_lines.append("")
    summary_lines.append("Rejection reason counts:")
    for k, v in sorted(rejection_counts.items(), key=lambda x: -x[1]):
        summary_lines.append(f"  {k}: {v}")
    summary_lines.append("")
    summary_lines.append("Rejection samples (first 200):")
    summary_lines.extend(f"{rid}\t{reason}" for rid, reason in rejection_samples)
    LOG.write_text("\n".join(summary_lines))
    print(f"round2: templates={len(ALL_TEMPLATES)} attempts={total_attempts} accepted={len(out)}")
    print("Per-bucket accepted:", bucket_accepted)
    print("Reject top:", dict(sorted(rejection_counts.items(), key=lambda x: -x[1])[:10]))


if __name__ == "__main__":
    main()
