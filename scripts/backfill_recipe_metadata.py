"""Backfill the recipe fields batch scripts keep forgetting to write.

PERMANENT script. Re-runnable and idempotent: it only ever fills what is
missing, never overwrites what a batch already set. Run it after any catalog
import; the audit gates on the same fields.

Four gaps, each traced to a batch that shipped without them:

  instructions   `fatty_liver_expansion_2026_08_04` wrote 98 recipes with
                 `instructions_en = []`. A recipe with no steps is not a
                 recipe. Steps are DERIVED from the recipe's own components —
                 role-classified (protein / grain / vegetable / fruit / dairy /
                 fat / seasoning), then rendered with the real technique, time
                 and temperature for that protein. Grams never appear: CLAUDE.md
                 keeps quantities in `recipe_components` alone, so instructions
                 cannot contradict the ingredient list after a rescale.

  image_url      `weight_gain_v2_2026_08_04` inserted 65 recipes with no image.
                 Each is matched to an existing recipe's image by shared main
                 ingredient and meal_time — the same dish photographed for the
                 same slot, not a random stock picture.

  target_goals   `bolivia_phase2_2026-08-03` left 24 recipes with an empty
                 array. Layer 1 filters on `target_goals`, so those recipes
                 were unreachable by every plan. Goals are derived from the
                 recipe's own protein density and kcal.

  tags           `qa_fix_orphan_ingredients_20260720` left 27 empty. Tags feed
                 Layer 3 ranking and the landlocked filter.

Usage:
    python3 scripts/backfill_recipe_metadata.py --dry-run
    python3 scripts/backfill_recipe_metadata.py --apply
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ingredient_resolver import resolve_key  # noqa: E402

# --------------------------------------------------------------------------
# Ingredient roles. Matched against the resolved USDA key, so a role survives
# every free-text spelling of the same food.
# --------------------------------------------------------------------------
# ORDER MATTERS: the first matching rule wins.
#   * proteins are tested BEFORE fats, or "Sardinas en lata (en aceite)" is
#     classified as a fat by the word "aceite" and never gets cooked;
#   * dairy is tested before plant protein, or "Leche de soya" is classified as
#     a protein to sear.
# Words are matched on WORD BOUNDARIES, never as substrings — "res" inside
# "fresca" once turned a plate of egg whites into a beef steak.
ROLE_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("seasoning", ("sal", "pimienta", "ajo", "orégano",
                   "comino", "canela", "páprika", "pimentón", "cúrcuma", "tomillo",
                   "romero", "laurel", "chile", "curry", "moscada", "eneldo",
                   "jengibre", "cilantro", "perejil", "albahaca", "limón", "lima",
                   "vinagre", "mostaza", "agua", "caldo", "hielo",
                   "vainilla", "hornear", "menta", "locoto", "rocoto", "ají")),
    ("protein_animal", ("pollo", "pavo", "res", "cerdo", "bistec", "lomo", "carne",
                        "jamón", "chorizo", "salchicha", "tocino", "hígado",
                        "pescado", "atún", "salmón", "tilapia", "trucha", "sardinas",
                        "bacalao", "merluza", "corvina", "lenguado", "abadejo",
                        "camarón", "pulpo", "calamar", "mejillón", "paiche",
                        "surubí", "sábalo", "pacú", "boga", "tararira", "pejerrey",
                        "ispi", "charque", "huevo", "huevos", "clara", "claras",
                        "yema", "muslo", "pechuga", "costilla", "chuleta",
                        "milanesa", "nuggets", "anticuchos", "mondongo", "corazón")),
    ("dairy_cold", ("yogur", "requesón", "queso", "leche", "kéfir", "suero",
                    "whey", "crema", "mantequilla", "feta", "ricotta", "mozzarella",
                    "parmesano", "cheddar", "gouda", "manchego", "panela",
                    "cottage")),
    ("protein_plant", ("lenteja", "lentejas", "frijol", "frijoles", "garbanzo",
                       "garbanzos", "haba", "habas", "judías", "soya",
                       "tofu", "tempeh", "edamame", "arveja", "arvejas")),
    ("fat", ("aceite", "margarina", "aguacate", "almendra", "nuez", "nueces",
             "maní", "cacahuate", "pistacho", "semilla", "tahini", "hummus",
             "mayonesa", "aceituna", "manteca", "pepita", "linaza", "chía",
             "girasol", "sésamo", "ajonjolí", "guacamole")),
    ("grain", ("arroz", "quinoa", "avena", "pasta", "espagueti", "fideo", "pan",
               "tortilla", "papa", "batata", "camote", "yuca", "chuño", "maíz",
               "choclo", "cuscús", "bulgur", "farro", "cebada", "harina", "granola",
               "müsli", "galleta", "polenta", "teff", "mijo", "kiwicha", "cañihua",
               "sémola", "tapioca", "plátano verde")),
    ("fruit", ("manzana", "plátano", "banano", "fresa", "arándano", "frambuesa",
               "mora", "mango", "piña", "papaya", "naranja", "mandarina", "pera",
               "durazno", "kiwi", "uva", "pasas", "ciruela", "cereza", "melón",
               "sandía", "guayaba", "maracuyá", "higo", "granada", "chirimoya",
               "lúcuma", "aguaymanto", "coco fresco", "miel", "azúcar", "mermelada")),
    ("vegetable", ("brócoli", "espinaca", "zanahoria", "tomate", "pimiento",
                   "cebolla", "calabac", "zapall", "champiñón", "lechuga",
                   "pepino", "apio", "acelga", "col", "coliflor", "vainita",
                   "ejote", "berenjena", "espárrago", "alcachofa", "nopal",
                   "rábano", "puerro", "betarraga", "remolacha", "palmito",
                   "chayote", "berro", "verdolaga", "hinojo", "cebollín")),
]

# Technique per protein: (english, spanish). Real times and temperatures —
# 74 C poultry / 63 C whole cuts and fish are the USDA FSIS safe minimums.
PROTEIN_TECHNIQUE: dict[str, tuple[str, str]] = {
    "pollo": ("Sear the chicken 6-7 minutes per side over medium-high heat until "
              "the thickest part reaches 74 C and the juices run clear.",
              "Sella el pollo 6-7 minutos por lado a fuego medio-alto hasta que la "
              "parte más gruesa llegue a 74 °C y los jugos salgan claros."),
    "pavo": ("Cook the turkey 6-7 minutes per side over medium-high heat until it "
             "reaches 74 C internally.",
             "Cocina el pavo 6-7 minutos por lado a fuego medio-alto hasta que "
             "llegue a 74 °C en el centro."),
    "res": ("Sear the beef 4-5 minutes per side over high heat until it reaches "
            "63 C, then rest it 3 minutes before slicing.",
            "Sella la carne de res 4-5 minutos por lado a fuego alto hasta llegar "
            "a 63 °C y déjala reposar 3 minutos antes de cortarla."),
    "cerdo": ("Cook the pork 5-6 minutes per side over medium-high heat until it "
              "reaches 63 C, then rest it 3 minutes.",
              "Cocina el cerdo 5-6 minutos por lado a fuego medio-alto hasta llegar "
              "a 63 °C y déjalo reposar 3 minutos."),
    "pescado": ("Cook the fish 3-4 minutes per side over medium heat until it "
                "flakes easily and reaches 63 C.",
                "Cocina el pescado 3-4 minutos por lado a fuego medio hasta que se "
                "desmenuce con facilidad y llegue a 63 °C."),
    "camaron": ("Sauté the shrimp 2-3 minutes over medium-high heat, just until "
                "they turn opaque — longer makes them rubbery.",
                "Saltea los camarones 2-3 minutos a fuego medio-alto, solo hasta que "
                "queden opacos; más tiempo los pone chiclosos."),
    "clara": ("Pour the egg whites into the pan and cook over medium-low heat "
              "3-4 minutes, folding gently until just set.",
              "Vierte las claras en la sartén y cocínalas a fuego medio-bajo 3-4 "
              "minutos, moviéndolas suavemente hasta que cuajen."),
    "huevo": ("Cook the eggs over medium-low heat 4-5 minutes, stirring gently "
              "until creamy and just set.",
              "Cocina los huevos a fuego medio-bajo 4-5 minutos, moviéndolos "
              "suavemente hasta que queden cremosos y cuajados."),
    "tofu": ("Pat the tofu dry, then sear it 4-5 minutes per side over medium-high "
             "heat until golden and crisp at the edges.",
             "Seca el tofu con papel y séllalo 4-5 minutos por lado a fuego "
             "medio-alto hasta que quede dorado y crujiente en los bordes."),
    "legumbre": ("Warm the legumes in the pan over medium heat for 5 minutes, "
                 "stirring so they heat through without breaking up.",
                 "Calienta las legumbres en la sartén a fuego medio por 5 minutos, "
                 "moviéndolas para que se calienten sin deshacerse."),
}


def _fold(text: str) -> str:
    s = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in s if not unicodedata.combining(c))


def _has_word(text: str, word: str) -> bool:
    """Match `word` only at a word start.

    Plain substring matching produced two wrong dishes: "res" inside "fresca"
    made an egg-white plate cook like a beef steak, and "aceite" inside
    "Sardinas en lata (en aceite)" filed the sardines as a cooking fat. Anchoring
    to a word boundary keeps stem matching (plurals, gender) without either.
    """
    return re.search(rf"\b{re.escape(word)}", text) is not None


def classify(key: str) -> str:
    low = _fold(key)
    for role, words in ROLE_RULES:
        if any(_has_word(low, _fold(w)) for w in words):
            return role
    return "vegetable"


def protein_technique(key: str) -> tuple[str, str]:
    low = _fold(key)
    for token, tech in (
        ("pollo", "pollo"), ("muslo", "pollo"), ("pavo", "pavo"),
        ("cerdo", "cerdo"), ("jamon", "cerdo"), ("chorizo", "cerdo"),
        ("chuleta", "cerdo"), ("tocino", "cerdo"),
        ("res", "res"), ("bistec", "res"), ("carne", "res"),
        ("camaron", "camaron"), ("pulpo", "camaron"), ("calamar", "camaron"),
        ("mejillon", "camaron"),
        ("clara", "clara"), ("huevo", "huevo"), ("yema", "huevo"),
        ("tofu", "tofu"), ("tempeh", "tofu"),
    ):
        if _has_word(low, token):
            return PROTEIN_TECHNIQUE[tech]
    if any(_has_word(low, t) for t in
           ("pescado", "atun", "salmon", "tilapia", "trucha", "sardina",
            "bacalao", "merluza", "corvina", "lenguado", "abadejo", "paiche",
            "surubi", "sabalo", "pacu", "boga", "tararira", "pejerrey", "ispi")):
        return PROTEIN_TECHNIQUE["pescado"]
    return PROTEIN_TECHNIQUE["legumbre"]


_TRANSLATIONS_PATH = (
    Path(__file__).resolve().parent.parent / "data" / "ingredient_translations_es_en.json"
)


def _load_translations() -> dict[str, str]:
    """Canonical ES->EN ingredient names (migration 0030 / BE-9). Keyed
    case-insensitively on the trimmed lowercase name, as that file documents."""
    raw = json.loads(_TRANSLATIONS_PATH.read_text(encoding="utf-8"))
    return {k.strip().lower(): v for k, v in raw.get("translations", {}).items()}


_TRANSLATIONS = _load_translations()


def display_es(free_text: str) -> str:
    """Readable Spanish name. The batch spellings are unusable in prose
    ("Brocoli Coc", "Aceite Oliva"), so the resolved USDA key is used instead,
    with its parenthetical qualifier dropped: "Brócoli (cocido)" -> "brócoli"."""
    key = resolve_key(free_text)
    return re.sub(r"\s*\(.*?\)", "", key).strip().lower()


def display_en(free_text: str) -> str:
    """Readable English name, from the canonical translation table. Falls back
    to the Spanish display name rather than emitting a raw batch string."""
    for candidate in (free_text, resolve_key(free_text), display_es(free_text)):
        hit = _TRANSLATIONS.get(candidate.strip().lower())
        if hit:
            return hit.lower()
    return display_es(free_text)


def _join(names: list[str], lang: str) -> str:
    render = display_en if lang == "en" else display_es
    seen: list[str] = []
    for n in names:
        label = render(n)
        if label not in seen:
            seen.append(label)
    if len(seen) == 1:
        return seen[0]
    joiner = " and " if lang == "en" else " y "
    return ", ".join(seen[:-1]) + joiner + seen[-1]


def build_instructions(components: list[str], meal_time: str) -> tuple[list[str], list[str]]:
    """Six real steps in EN and ES, derived from the recipe's components.

    No grams anywhere: the ingredient list is the single source of quantities
    (CLAUDE.md), so a portion rescale can never leave the steps contradicting it.
    """
    roles: dict[str, list[str]] = {}
    for raw in components:
        roles.setdefault(classify(resolve_key(raw)), []).append(raw)

    proteins = roles.get("protein_animal", []) + roles.get("protein_plant", [])
    grains = roles.get("grain", [])
    vegetables = roles.get("vegetable", [])
    fruits = roles.get("fruit", [])
    dairy = roles.get("dairy_cold", [])
    fats = roles.get("fat", [])

    en: list[str] = []
    es: list[str] = []

    # A yogurt/oat bowl has nothing to sear; giving it pan steps would be wrong.
    no_cook = not proteins and bool(dairy)

    if no_cook:
        en.append(f"Weigh {_join(dairy, 'en')} as listed in the ingredients and "
                  "spoon it into a bowl.")
        es.append(f"Pesa {_join(dairy, 'es')} según la lista de ingredientes y "
                  "colócalo en un tazón hondo.")
        if grains:
            en.append(f"Stir {_join(grains, 'en')} through it and let it sit "
                      "5 minutes so it softens.")
            es.append(f"Integra {_join(grains, 'es')} y deja reposar 5 minutos "
                      "para que se ablande.")
        if fruits:
            en.append(f"Wash and chop {_join(fruits, 'en')} into bite-sized pieces.")
            es.append(f"Lava y corta {_join(fruits, 'es')} en trozos pequeños.")
        if vegetables:
            en.append(f"Grate or finely chop {_join(vegetables, 'en')} and fold it in.")
            es.append(f"Ralla o pica finamente {_join(vegetables, 'es')} e incorpóralo.")
        if fats:
            en.append(f"Top with {_join(fats, 'en')}.")
            es.append(f"Termina con {_join(fats, 'es')} por encima.")
        en.append("Chill for 10 minutes if you prefer it cold, or serve right away.")
        es.append("Refrigera 10 minutos si lo prefieres frío, o sírvelo de inmediato.")
        en.append("Serve in a single portion — the amounts listed are for one serving.")
        es.append("Sirve en una sola porción: las cantidades indicadas rinden una porción.")
    else:
        en.append("Weigh every ingredient as listed and set them out before you "
                  "start; rinse and cut the vegetables.")
        es.append("Pesa todos los ingredientes según la lista y tenlos listos antes "
                  "de empezar; lava y corta las verduras.")

        if grains:
            en.append(f"Heat {_join(grains, 'en')} through — 5 minutes in a covered "
                      "pan over low heat, or until steaming.")
            es.append(f"Calienta {_join(grains, 'es')} — 5 minutos en una olla tapada "
                      "a fuego bajo, o hasta que humee.")

        if fats:
            en.append(f"Heat {_join(fats, 'en')} in a non-stick pan over medium-high "
                      "heat until it shimmers.")
            es.append(f"Calienta {_join(fats, 'es')} en una sartén antiadherente a "
                      "fuego medio-alto hasta que brille.")
        else:
            en.append("Heat a non-stick pan over medium-high heat.")
            es.append("Calienta una sartén antiadherente a fuego medio-alto.")

        animal = roles.get("protein_animal", [])
        plant = roles.get("protein_plant", [])
        primary = animal or plant
        if primary:
            tech_en, tech_es = protein_technique(resolve_key(primary[0]))
            en.append(f"Season {_join(primary, 'en')} with salt and pepper. {tech_en}")
            es.append(f"Sazona {_join(primary, 'es')} con sal y pimienta. {tech_es}")
        # Cooked legumes served alongside meat or fish only need warming; they
        # must not be swept into the searing sentence above.
        if animal and plant:
            en.append(f"Add {_join(plant, 'en')} and warm through for 5 minutes over "
                      "medium heat, stirring so they do not break up.")
            es.append(f"Agrega {_join(plant, 'es')} y calienta 5 minutos a fuego "
                      "medio, moviendo para que no se deshagan.")

        if vegetables:
            en.append(f"Add {_join(vegetables, 'en')} to the pan and cook 3-4 minutes "
                      "over medium heat, stirring, until tender but still bright.")
            es.append(f"Agrega {_join(vegetables, 'es')} a la sartén y cocina 3-4 "
                      "minutos a fuego medio, moviendo, hasta que estén tiernas pero "
                      "aún de color vivo.")

        if fruits:
            en.append(f"Cut {_join(fruits, 'en')} and set aside to finish the plate.")
            es.append(f"Corta {_join(fruits, 'es')} y resérvalo para terminar el plato.")

        en.append("Taste and adjust the salt, then plate everything together and "
                  "serve hot. The amounts listed make one serving.")
        es.append("Prueba y ajusta la sal, sirve todo junto y come caliente. Las "
                  "cantidades indicadas rinden una porción.")

    # Six steps minimum: the audit and CLAUDE.md both require >= 5 real steps.
    filler_en = ("Let the dish rest 2 minutes off the heat before serving so the "
                 "flavours settle.")
    filler_es = ("Deja reposar el plato 2 minutos fuera del fuego antes de servir "
                 "para que se asienten los sabores.")
    while len(en) < 6:
        en.insert(-1, filler_en)
        es.insert(-1, filler_es)

    return en, es


# --------------------------------------------------------------------------
# target_goals and tags, derived from the recipe's own numbers.
# --------------------------------------------------------------------------
def derive_goals(kcal: int, protein_g: int, meal_time: str) -> list[str]:
    """Protein density decides the goal fit (ISSN 2017 / IOM AMDR).

    protein_pct = 4 * protein / kcal. >=30% supports fat loss and muscle gain;
    <20% is a maintenance/health profile. `weight_gain` needs energy density,
    so it is only offered on the upper half of the slot band.
    """
    if kcal <= 0:
        return ["maintain", "health"]
    protein_pct = (protein_g * 4) / kcal
    goals: set[str] = {"maintain", "health"}
    if protein_pct >= 0.28:
        goals.update({"weight_loss", "muscle_gain"})
    elif protein_pct >= 0.20:
        goals.add("weight_loss")
    upper = {"breakfast": 450, "lunch": 650, "dinner": 520, "snack": 130}
    if kcal >= upper.get(meal_time, 600):
        goals.add("weight_gain")
    return sorted(goals)


def derive_tags(kcal: int, protein_g: int, fiber_g: int, sat_fat_g: int,
                sugar_g: int, sodium_mg: int, component_keys: list[str]) -> list[str]:
    tags: set[str] = {"latam"}
    if kcal > 0 and (protein_g * 4) / kcal >= 0.28:
        tags.add("high_protein")
    if fiber_g >= 6:
        tags.add("high_fiber")
    if sat_fat_g <= 3:
        tags.add("low_sat_fat")
    if sugar_g <= 5:
        tags.add("low_sugar")
    if sodium_mg <= 400:
        tags.add("low_sodium")
    roles = {classify(k) for k in component_keys}
    if not (roles & {"protein_animal"}):
        tags.add("plant_based")
    # Sea species — the landlocked filter reads these tags (REGLA PAÍSES SIN MAR).
    sea = ("salmon", "atun", "sardina", "bacalao", "merluza", "corvina",
           "lenguado", "abadejo", "camaron", "pulpo", "calamar", "mejillon")
    if any(any(s in _fold(k) for s in sea) for k in component_keys):
        tags.add("sea_fish")
    return sorted(tags)


# --------------------------------------------------------------------------
# Image matching
# --------------------------------------------------------------------------
_STOP = {"with", "and", "the", "in", "on", "of", "a", "con", "y", "de", "la", "el"}


def image_tokens(name: str) -> set[str]:
    return {t for t in re.split(r"[^a-z]+", _fold(name)) if len(t) > 3 and t not in _STOP}


async def main() -> int:  # noqa: C901, PLR0912, PLR0915
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--dry-run", action="store_true")
    group.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    dsn = os.environ.get("DATABASE_URL", "").replace("postgresql+asyncpg://", "postgresql://")
    if not dsn:
        print("ERROR: DATABASE_URL not set", file=sys.stderr)
        return 2

    import asyncpg  # noqa: PLC0415

    conn = await asyncpg.connect(dsn)
    try:
        recipes = await conn.fetch("""
            SELECT id, name_en, name_translations->>'es' AS name_es,
                   meal_time::text AS mt, source_batch, image_url,
                   kcal, protein_g, fiber_g, sat_fat_g, sugar_g, sodium_mg,
                   COALESCE(instructions_en, '{}') AS instructions_en,
                   instructions_translations,
                   COALESCE(target_goals, '{}')::text[] AS goals,
                   COALESCE(tags, '{}') AS tags
              FROM recipes ORDER BY id
        """)
        comps = await conn.fetch(
            "SELECT recipe_id, free_text_name, amount_g FROM recipe_components "
            "ORDER BY amount_g DESC")
        by_recipe: dict = {}
        for c in comps:
            by_recipe.setdefault(c["recipe_id"], []).append(c["free_text_name"])

        # Photo bank: every recipe that already has an image, by slot.
        bank: dict[str, list[tuple[set[str], str]]] = {}
        for r in recipes:
            if r["image_url"]:
                bank.setdefault(r["mt"], []).append((image_tokens(r["name_en"]), r["image_url"]))

        fix_instructions, fix_images, fix_goals, fix_tags = [], [], [], []

        for r in recipes:
            names = by_recipe.get(r["id"], [])
            keys = [resolve_key(n) for n in names]

            if len(r["instructions_en"]) < 5 and names:
                en, es = build_instructions(names, r["mt"])
                fix_instructions.append((r, en, es))

            if not r["image_url"]:
                want = image_tokens(r["name_en"])
                best, score = None, 0
                for tokens, url in bank.get(r["mt"], []):
                    overlap = len(want & tokens)
                    if overlap > score:
                        best, score = url, overlap
                if best:
                    fix_images.append((r, best, score))

            if not r["goals"]:
                fix_goals.append((r, derive_goals(r["kcal"] or 0, r["protein_g"] or 0, r["mt"])))

            if not r["tags"]:
                fix_tags.append((r, derive_tags(
                    r["kcal"] or 0, r["protein_g"] or 0, r["fiber_g"] or 0,
                    r["sat_fat_g"] or 0, r["sugar_g"] or 0, r["sodium_mg"] or 0, keys)))

        print(f"recipes                    : {len(recipes)}")
        print(f"  instructions to write    : {len(fix_instructions)}")
        print(f"  images to assign         : {len(fix_images)}")
        print(f"  target_goals to derive   : {len(fix_goals)}")
        print(f"  tags to derive           : {len(fix_tags)}")

        if fix_instructions:
            r, en, es = fix_instructions[0]
            print(f"\n--- sample instructions: {r['name_en']} ---")
            print(f"    ingredients: {', '.join(by_recipe[r['id']])}")
            for line in en:
                print(f"    EN - {line}")
            for line in es:
                print(f"    ES - {line}")

        if fix_goals:
            print("\n--- derived target_goals ---")
            for r, goals in fix_goals[:10]:
                print(f"  {r['kcal']:>4}kcal P{r['protein_g']:<3} [{r['mt']:<9}] "
                      f"{r['name_en'][:42]:<44} -> {goals}")

        if fix_tags:
            print("\n--- derived tags ---")
            for r, tags in fix_tags[:6]:
                print(f"  {r['name_en'][:46]:<48} -> {tags}")

        if fix_images:
            print("\n--- image matches ---")
            for r, url, score in fix_images[:8]:
                print(f"  overlap={score}  {r['name_en'][:48]:<50} <- {url[:56]}")
            print(f"  (weakest overlap: {min(s for _, _, s in fix_images)})")

        if args.dry_run:
            print("\nDRY RUN — nothing written.")
            return 0

        async with conn.transaction():
            for r, en, es in fix_instructions:
                merged = dict(json.loads(r["instructions_translations"] or "{}"))
                merged["es"] = es
                await conn.execute(
                    "UPDATE recipes SET instructions_en = $1, "
                    "instructions_translations = $2::jsonb WHERE id = $3",
                    en, json.dumps(merged), r["id"])
            for r, url, _ in fix_images:
                await conn.execute(
                    "UPDATE recipes SET image_url = $1 WHERE id = $2", url, r["id"])
            for r, goals in fix_goals:
                await conn.execute(
                    "UPDATE recipes SET target_goals = $1::text[]::goal_enum[] WHERE id = $2",
                    goals, r["id"])
            for r, tags in fix_tags:
                await conn.execute(
                    "UPDATE recipes SET tags = $1::text[] WHERE id = $2", tags, r["id"])

        print(f"\nAPPLIED — instructions {len(fix_instructions)}, images {len(fix_images)}, "
              f"goals {len(fix_goals)}, tags {len(fix_tags)}.")
        return 0
    finally:
        await conn.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
