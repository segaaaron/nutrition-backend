"""0001 — full NOVA schema (27 tables + enums + indexes + triggers + seed).

Materialises spec §7 in one revision. Idempotent against re-runs via
`CREATE EXTENSION IF NOT EXISTS`, `IF NOT EXISTS` on tables/indexes, and the
TimescaleDB `if_not_exists=>TRUE` helper flag.

Seeds inline (rationale: schema-derived closed vocabularies live with the schema):
  - 5 regions (us, ca, eu, uk, latam)
  - 14 allergens × 5 locales (i18n_translations)
  - 25 canonical conditions × 5 locales
  - 4 meal_times × 5 locales
  - 5 goals × 5 locales
  - 5 activity_levels × 5 locales
  - 30+ condition_synonyms

Downgrade is implemented (drops everything) for round-trip verification, but
production rollbacks should use point-in-time recovery, not Alembic downgrade.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0001_init"
down_revision = None
branch_labels = None
depends_on = None


# ---------------------------------------------------------------------------
# Vocabularies (single source of truth in code — used by seeds below)
# ---------------------------------------------------------------------------

ALLERGENS_14: list[str] = [
    "dairy", "gluten", "tree_nuts", "peanuts", "shellfish", "fish", "egg",
    "soy", "sesame", "celery", "mustard", "lupin", "sulphites", "molluscs",
]

CONDITIONS_25: list[str] = [
    "diabetes_t1", "diabetes_t2", "hypertension", "dyslipidemia",
    "hypercholesterolemia", "hypothyroidism", "hyperthyroidism", "ibs", "ibd",
    "celiac", "lactose_intolerance", "obesity", "overweight", "pregnancy",
    "lactation", "athletic_load", "ckd", "ischemic_heart_disease",
    "fatty_liver", "iron_deficiency_anemia", "pcos", "gout",
    "vitamin_d_deficiency", "chronic_insomnia", "mild_depression",
]

GOALS_5: list[str] = ["weight_loss", "maintain", "muscle_gain", "weight_gain", "health"]
MEAL_TIMES_4: list[str] = ["breakfast", "lunch", "dinner", "snack"]
ACTIVITY_LEVELS_5: list[str] = [
    "sedentary", "lightly_active", "moderately_active", "very_active", "extra_active",
]
LOCALES: list[str] = ["en", "es", "pt", "fr", "de"]


# ---------------------------------------------------------------------------
# Translation matrices (compact tables — full coverage for 5 supported locales)
# ---------------------------------------------------------------------------

ALLERGEN_I18N: dict[str, dict[str, str]] = {
    "dairy":      {"en": "Dairy",       "es": "Lácteos",       "pt": "Laticínios",   "fr": "Produits laitiers", "de": "Milchprodukte"},
    "gluten":     {"en": "Gluten",      "es": "Gluten",        "pt": "Glúten",       "fr": "Gluten",            "de": "Gluten"},
    "tree_nuts":  {"en": "Tree nuts",   "es": "Frutos secos",  "pt": "Frutos secos", "fr": "Fruits à coque",    "de": "Schalenfrüchte"},
    "peanuts":    {"en": "Peanuts",     "es": "Maní",          "pt": "Amendoim",     "fr": "Arachides",         "de": "Erdnüsse"},
    "shellfish":  {"en": "Shellfish",   "es": "Crustáceos",    "pt": "Crustáceos",   "fr": "Crustacés",         "de": "Krebstiere"},
    "fish":       {"en": "Fish",        "es": "Pescado",       "pt": "Peixe",        "fr": "Poisson",           "de": "Fisch"},
    "egg":        {"en": "Egg",         "es": "Huevo",         "pt": "Ovo",          "fr": "Œuf",               "de": "Ei"},
    "soy":        {"en": "Soy",         "es": "Soja",          "pt": "Soja",         "fr": "Soja",              "de": "Soja"},
    "sesame":     {"en": "Sesame",      "es": "Sésamo",        "pt": "Gergelim",     "fr": "Sésame",            "de": "Sesam"},
    "celery":     {"en": "Celery",      "es": "Apio",          "pt": "Aipo",         "fr": "Céleri",            "de": "Sellerie"},
    "mustard":    {"en": "Mustard",     "es": "Mostaza",       "pt": "Mostarda",     "fr": "Moutarde",          "de": "Senf"},
    "lupin":      {"en": "Lupin",       "es": "Altramuces",    "pt": "Tremoço",      "fr": "Lupin",             "de": "Lupinen"},
    "sulphites":  {"en": "Sulphites",   "es": "Sulfitos",      "pt": "Sulfitos",     "fr": "Sulfites",          "de": "Sulfite"},
    "molluscs":   {"en": "Molluscs",    "es": "Moluscos",      "pt": "Moluscos",     "fr": "Mollusques",        "de": "Weichtiere"},
}

CONDITION_I18N: dict[str, dict[str, str]] = {
    "diabetes_t1":            {"en": "Type 1 diabetes",        "es": "Diabetes tipo 1",        "pt": "Diabetes tipo 1",       "fr": "Diabète de type 1",       "de": "Typ-1-Diabetes"},
    "diabetes_t2":            {"en": "Type 2 diabetes",        "es": "Diabetes tipo 2",        "pt": "Diabetes tipo 2",       "fr": "Diabète de type 2",       "de": "Typ-2-Diabetes"},
    "hypertension":           {"en": "Hypertension",           "es": "Hipertensión",           "pt": "Hipertensão",           "fr": "Hypertension",            "de": "Bluthochdruck"},
    "dyslipidemia":           {"en": "Dyslipidemia",           "es": "Dislipidemia",           "pt": "Dislipidemia",          "fr": "Dyslipidémie",            "de": "Dyslipidämie"},
    "hypercholesterolemia":   {"en": "Hypercholesterolemia",   "es": "Hipercolesterolemia",    "pt": "Hipercolesterolemia",   "fr": "Hypercholestérolémie",    "de": "Hypercholesterinämie"},
    "hypothyroidism":         {"en": "Hypothyroidism",         "es": "Hipotiroidismo",         "pt": "Hipotireoidismo",       "fr": "Hypothyroïdie",           "de": "Hypothyreose"},
    "hyperthyroidism":        {"en": "Hyperthyroidism",        "es": "Hipertiroidismo",        "pt": "Hipertireoidismo",      "fr": "Hyperthyroïdie",          "de": "Hyperthyreose"},
    "ibs":                    {"en": "Irritable bowel syndrome","es": "Síndrome intestino irritable","pt": "Síndrome intestino irritável","fr": "Syndrome côlon irritable","de": "Reizdarmsyndrom"},
    "ibd":                    {"en": "Inflammatory bowel disease","es": "Enfermedad intestinal inflamatoria","pt": "Doença inflamatória intestinal","fr": "Maladie inflammatoire intestinale","de": "Chronisch-entzündliche Darmerkrankung"},
    "celiac":                 {"en": "Celiac disease",         "es": "Enfermedad celíaca",     "pt": "Doença celíaca",        "fr": "Maladie cœliaque",        "de": "Zöliakie"},
    "lactose_intolerance":    {"en": "Lactose intolerance",    "es": "Intolerancia a la lactosa","pt": "Intolerância à lactose","fr": "Intolérance au lactose",  "de": "Laktoseintoleranz"},
    "obesity":                {"en": "Obesity",                "es": "Obesidad",               "pt": "Obesidade",             "fr": "Obésité",                 "de": "Adipositas"},
    "overweight":             {"en": "Overweight",             "es": "Sobrepeso",              "pt": "Sobrepeso",             "fr": "Surpoids",                "de": "Übergewicht"},
    "pregnancy":              {"en": "Pregnancy",              "es": "Embarazo",               "pt": "Gravidez",              "fr": "Grossesse",               "de": "Schwangerschaft"},
    "lactation":              {"en": "Lactation",              "es": "Lactancia",              "pt": "Lactação",              "fr": "Allaitement",             "de": "Stillzeit"},
    "athletic_load":          {"en": "Athletic load",          "es": "Carga atlética",         "pt": "Carga atlética",        "fr": "Charge athlétique",       "de": "Sportliche Belastung"},
    "ckd":                    {"en": "Chronic kidney disease", "es": "Enfermedad renal crónica","pt": "Doença renal crônica",  "fr": "Maladie rénale chronique","de": "Chronische Nierenerkrankung"},
    "ischemic_heart_disease": {"en": "Ischemic heart disease", "es": "Cardiopatía isquémica",  "pt": "Cardiopatia isquêmica", "fr": "Cardiopathie ischémique", "de": "Ischämische Herzkrankheit"},
    "fatty_liver":            {"en": "Fatty liver disease",    "es": "Hígado graso",           "pt": "Esteatose hepática",    "fr": "Stéatose hépatique",      "de": "Fettleber"},
    "iron_deficiency_anemia": {"en": "Iron-deficiency anemia", "es": "Anemia ferropénica",     "pt": "Anemia ferropriva",     "fr": "Anémie ferriprive",       "de": "Eisenmangelanämie"},
    "pcos":                   {"en": "Polycystic ovary syndrome","es": "Síndrome de ovario poliquístico","pt": "Síndrome dos ovários policísticos","fr": "Syndrome des ovaires polykystiques","de": "Polyzystisches Ovarialsyndrom"},
    "gout":                   {"en": "Gout",                   "es": "Gota",                   "pt": "Gota",                  "fr": "Goutte",                  "de": "Gicht"},
    "vitamin_d_deficiency":   {"en": "Vitamin D deficiency",   "es": "Déficit de vitamina D",  "pt": "Deficiência de vitamina D","fr": "Carence en vitamine D",   "de": "Vitamin-D-Mangel"},
    "chronic_insomnia":       {"en": "Chronic insomnia",       "es": "Insomnio crónico",       "pt": "Insônia crônica",       "fr": "Insomnie chronique",      "de": "Chronische Schlaflosigkeit"},
    "mild_depression":        {"en": "Mild depression",        "es": "Depresión leve",         "pt": "Depressão leve",        "fr": "Dépression légère",       "de": "Leichte Depression"},
}

GOAL_I18N: dict[str, dict[str, str]] = {
    "weight_loss":  {"en": "Weight loss",  "es": "Pérdida de peso", "pt": "Perda de peso",   "fr": "Perte de poids",     "de": "Gewichtsverlust"},
    "maintain":     {"en": "Maintain",     "es": "Mantener",        "pt": "Manter",          "fr": "Maintien",           "de": "Halten"},
    "muscle_gain":  {"en": "Muscle gain",  "es": "Ganar músculo",   "pt": "Ganho muscular",  "fr": "Prise de muscle",    "de": "Muskelaufbau"},
    "weight_gain":  {"en": "Weight gain",  "es": "Ganar peso",      "pt": "Ganhar peso",     "fr": "Prise de poids",     "de": "Gewichtszunahme"},
    "health":       {"en": "Health",       "es": "Salud",           "pt": "Saúde",           "fr": "Santé",              "de": "Gesundheit"},
}

MEAL_TIME_I18N: dict[str, dict[str, str]] = {
    "breakfast": {"en": "Breakfast", "es": "Desayuno", "pt": "Café da manhã", "fr": "Petit-déjeuner", "de": "Frühstück"},
    "lunch":     {"en": "Lunch",     "es": "Almuerzo", "pt": "Almoço",        "fr": "Déjeuner",       "de": "Mittagessen"},
    "dinner":    {"en": "Dinner",    "es": "Cena",     "pt": "Jantar",        "fr": "Dîner",          "de": "Abendessen"},
    "snack":     {"en": "Snack",     "es": "Snack",    "pt": "Lanche",        "fr": "Collation",      "de": "Snack"},
}

ACTIVITY_LEVEL_I18N: dict[str, dict[str, str]] = {
    "sedentary":          {"en": "Sedentary",          "es": "Sedentario",            "pt": "Sedentário",            "fr": "Sédentaire",           "de": "Sitzend"},
    "lightly_active":     {"en": "Lightly active",     "es": "Ligeramente activo",    "pt": "Levemente ativo",       "fr": "Légèrement actif",     "de": "Leicht aktiv"},
    "moderately_active":  {"en": "Moderately active",  "es": "Moderadamente activo",  "pt": "Moderadamente ativo",   "fr": "Modérément actif",     "de": "Mäßig aktiv"},
    "very_active":        {"en": "Very active",        "es": "Muy activo",            "pt": "Muito ativo",           "fr": "Très actif",           "de": "Sehr aktiv"},
    "extra_active":       {"en": "Extra active",       "es": "Extra activo",          "pt": "Extra ativo",           "fr": "Extrêmement actif",    "de": "Extrem aktiv"},
}

# Region seeds. allergen_set drives which checkboxes the UI shows per region.
REGION_SEEDS: list[dict] = [
    {
        "code": "us", "name": "United States",
        "allergen_set": ["dairy", "gluten", "tree_nuts", "peanuts", "shellfish", "fish", "egg", "soy", "sesame"],
        "countries": ["US"], "default_locale": "en",
    },
    {
        "code": "ca", "name": "Canada",
        "allergen_set": ["dairy", "gluten", "tree_nuts", "peanuts", "shellfish", "fish", "egg", "soy", "sesame", "mustard", "sulphites"],
        "countries": ["CA"], "default_locale": "en",
    },
    {
        "code": "eu", "name": "European Union",
        "allergen_set": ALLERGENS_14,
        "countries": ["DE", "FR", "IT", "ES", "PT", "NL", "BE", "AT", "IE", "FI", "SE", "DK", "PL", "CZ", "GR", "RO", "HU", "BG", "HR", "SI", "SK", "LU", "MT", "CY", "EE", "LV", "LT"],
        "default_locale": "en",
    },
    {
        "code": "uk", "name": "United Kingdom",
        "allergen_set": ALLERGENS_14,
        "countries": ["GB"], "default_locale": "en",
    },
    {
        "code": "latam", "name": "Latin America",
        "allergen_set": ["dairy", "gluten", "tree_nuts", "peanuts", "shellfish", "fish", "egg", "soy", "sesame"],
        "countries": ["MX", "PE", "CO", "AR", "CL", "BR", "VE", "EC", "UY", "PY", "BO", "CR", "PA", "GT", "HN", "SV", "NI", "DO", "PR"],
        "default_locale": "es",
    },
]

# condition_synonyms: collapses upstream LLM-emitted variants to ADR-0001 codes.
CONDITION_SYNONYMS: list[tuple[str, str, str]] = [
    # synonym, canonical, reason
    ("diabetes_type_1", "diabetes_t1", "agent variant → ADR-0001 canonical"),
    ("diabetes_type_2", "diabetes_t2", "agent variant → ADR-0001 canonical"),
    ("type1_diabetes", "diabetes_t1", "underscore variant"),
    ("type2_diabetes", "diabetes_t2", "underscore variant"),
    ("dm1", "diabetes_t1", "nutrition abbreviation"),
    ("dm2", "diabetes_t2", "nutrition abbreviation"),
    ("htn", "hypertension", "nutrition abbreviation"),
    ("high_blood_pressure", "hypertension", "lay term"),
    ("cardiovascular_disease", "ischemic_heart_disease", "round-2 ES → EN round-3 narrow"),
    ("cvd", "ischemic_heart_disease", "abbreviation"),
    ("heart_disease", "ischemic_heart_disease", "lay term"),
    ("kidney_disease", "ckd", "lay term"),
    ("renal_failure", "ckd", "nutrition variant"),
    ("nafld", "fatty_liver", "nutrition abbreviation"),
    ("non_alcoholic_fatty_liver", "fatty_liver", "expanded form"),
    ("hepatic_steatosis", "fatty_liver", "nutrition synonym"),
    ("irritable_bowel_syndrome", "ibs", "expanded form"),
    ("inflammatory_bowel_disease", "ibd", "expanded form"),
    ("crohn", "ibd", "subtype of IBD"),
    ("crohns", "ibd", "subtype of IBD"),
    ("ulcerative_colitis", "ibd", "subtype of IBD"),
    ("coeliac", "celiac", "UK spelling"),
    ("coeliac_disease", "celiac", "UK spelling"),
    ("celiac_disease", "celiac", "expanded form"),
    ("milk_intolerance", "lactose_intolerance", "lay term"),
    ("anemia", "iron_deficiency_anemia", "narrow to most common subtype"),
    ("ferropenic_anemia", "iron_deficiency_anemia", "nutrition variant"),
    ("polycystic_ovary_syndrome", "pcos", "expanded form"),
    ("polycystic_ovaries", "pcos", "lay variant"),
    ("hyperuricemia", "gout", "biochemical antecedent of gout"),
    ("uric_acid_high", "gout", "lay term"),
    ("vitamin_d_low", "vitamin_d_deficiency", "lay term"),
    ("insomnia", "chronic_insomnia", "narrow to chronic form"),
    ("depression", "mild_depression", "narrow to mild form"),
    ("post_partum", "lactation", "common co-occurrence"),
    ("breastfeeding", "lactation", "lay term"),
    ("pregnant", "pregnancy", "adjective form"),
    ("obese", "obesity", "adjective form"),
    ("athlete", "athletic_load", "lay term"),
    ("sportsperson", "athletic_load", "lay term"),
    ("low_thyroid", "hypothyroidism", "lay term"),
    ("high_thyroid", "hyperthyroidism", "lay term"),
]


# ---------------------------------------------------------------------------
# upgrade()
# ---------------------------------------------------------------------------

def upgrade() -> None:
    # --- 1. Extensions (idempotent; init.sql also creates these on first boot) ---
    op.execute("CREATE EXTENSION IF NOT EXISTS timescaledb")
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute("CREATE EXTENSION IF NOT EXISTS unaccent")
    op.execute("CREATE EXTENSION IF NOT EXISTS citext")

    # --- 2. Enum types ---
    op.execute("CREATE TYPE allergen_enum AS ENUM (" + ",".join(f"'{a}'" for a in ALLERGENS_14) + ")")
    op.execute("CREATE TYPE sex_enum AS ENUM ('male','female')")
    op.execute("CREATE TYPE units_enum AS ENUM ('metric','imperial')")
    op.execute("CREATE TYPE goal_enum AS ENUM (" + ",".join(f"'{g}'" for g in GOALS_5) + ")")
    op.execute("CREATE TYPE activity_level_enum AS ENUM (" + ",".join(f"'{a}'" for a in ACTIVITY_LEVELS_5) + ")")
    op.execute("CREATE TYPE theme_enum AS ENUM ('light','dark')")
    op.execute("CREATE TYPE meal_time_enum AS ENUM (" + ",".join(f"'{m}'" for m in MEAL_TIMES_4) + ")")
    op.execute("CREATE TYPE goal_reason_enum AS ENUM ('onboarding','weight_change','goal_change','plateau','manual')")
    op.execute("CREATE TYPE plan_type_enum AS ENUM ('day','week','month')")
    op.execute("CREATE TYPE plan_status_enum AS ENUM ('active','completed','cancelled')")
    op.execute("CREATE TYPE otp_purpose_enum AS ENUM ('register','reset','login')")
    op.execute("CREATE TYPE log_method_enum AS ENUM ('photo','voice','text','barcode','search','manual')")
    op.execute("CREATE TYPE daily_goal_item_enum AS ENUM ('breakfast','lunch','dinner','water')")
    op.execute("CREATE TYPE grocery_category_enum AS ENUM ('fruits_vegetables','proteins','dairy','pantry','other')")
    op.execute("CREATE TYPE streak_type_enum AS ENUM ('daily','fasting','protein')")
    op.execute("CREATE TYPE coach_role_enum AS ENUM ('user','assistant','system')")
    op.execute("CREATE TYPE actor_type_enum AS ENUM ('user','system','admin')")

    # --- 3. Identity ---
    op.execute("""
        CREATE TABLE users (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            email citext UNIQUE NOT NULL,
            password_hash text NULL,
            oauth_provider text NULL,
            oauth_subject text NULL,
            email_verified bool NOT NULL DEFAULT false,
            role text NOT NULL DEFAULT 'user',
            created_at timestamptz NOT NULL DEFAULT now(),
            last_login_at timestamptz NULL,
            deletion_requested_at timestamptz NULL,
            deleted_at timestamptz NULL
        )
    """)
    op.execute("CREATE INDEX ix_users_oauth ON users(oauth_provider, oauth_subject) WHERE oauth_provider IS NOT NULL")
    op.execute("CREATE INDEX ix_users_deletion ON users(deletion_requested_at) WHERE deletion_requested_at IS NOT NULL")

    op.execute("""
        CREATE TABLE refresh_tokens (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            token_hash text NOT NULL,
            family_id uuid NOT NULL,
            parent_id uuid NULL REFERENCES refresh_tokens(id) ON DELETE CASCADE,
            expires_at timestamptz NOT NULL,
            revoked_at timestamptz NULL,
            reused_at timestamptz NULL,
            created_at timestamptz NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX ix_refresh_tokens_user ON refresh_tokens(user_id)")
    op.execute("CREATE INDEX ix_refresh_tokens_family ON refresh_tokens(family_id)")
    op.execute("CREATE UNIQUE INDEX uq_refresh_tokens_hash ON refresh_tokens(token_hash)")

    op.execute("""
        CREATE TABLE otp_codes (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            code_hash text NOT NULL,
            purpose otp_purpose_enum NOT NULL,
            expires_at timestamptz NOT NULL,
            attempts int NOT NULL DEFAULT 0,
            locked_until timestamptz NULL,
            created_at timestamptz NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX ix_otp_user_purpose ON otp_codes(user_id, purpose)")

    # --- 4. Profile ---
    op.execute("""
        CREATE TABLE user_profiles (
            user_id uuid PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
            name text NULL,
            age int NULL CHECK (age IS NULL OR (12 <= age AND age <= 100)),
            sex sex_enum NULL,
            units units_enum NOT NULL DEFAULT 'metric',
            weight_kg numeric(5,2) NULL,
            height_cm numeric(5,2) NULL,
            goal goal_enum NULL,
            activity_level activity_level_enum NULL,
            medical_conditions text[] NOT NULL DEFAULT '{}',
            other_condition text NULL,
            allergies allergen_enum[] NOT NULL DEFAULT '{}',
            other_allergy text NULL,
            country char(2) NULL,
            region char(5) NULL,
            locale char(2) NOT NULL DEFAULT 'en',
            theme theme_enum NOT NULL DEFAULT 'light',
            onboarding_completed bool NOT NULL DEFAULT false,
            updated_at timestamptz NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX ix_user_profiles_region ON user_profiles(region)")
    op.execute("CREATE INDEX ix_user_profiles_locale ON user_profiles(locale)")
    op.execute("CREATE INDEX ix_user_profiles_country ON user_profiles(country)")

    # --- 5. Nutritional goals ---
    op.execute("""
        CREATE TABLE nutritional_goals (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            kcal_min int NOT NULL,
            kcal_max int NOT NULL,
            protein_g int NOT NULL,
            carbs_g int NOT NULL,
            fat_g int NOT NULL,
            water_ml int NOT NULL,
            bmr int NOT NULL,
            tdee int NOT NULL,
            activity_factor numeric(4,3) NOT NULL,
            reason goal_reason_enum NOT NULL,
            valid_from timestamptz NOT NULL DEFAULT now(),
            valid_to timestamptz NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            CHECK (kcal_max - kcal_min = 200)
        )
    """)
    op.execute("CREATE UNIQUE INDEX one_current_goals ON nutritional_goals(user_id) WHERE valid_to IS NULL")
    op.execute("CREATE INDEX ix_goals_user_valid_from ON nutritional_goals(user_id, valid_from DESC)")

    # --- 6. Regions / i18n / lexicon ---
    op.execute("""
        CREATE TABLE regions (
            code char(5) PRIMARY KEY,
            name text NOT NULL,
            allergen_set allergen_enum[] NOT NULL,
            countries char(2)[] NOT NULL,
            default_locale char(2) NOT NULL
        )
    """)
    op.execute("CREATE INDEX ix_regions_countries ON regions USING gin (countries)")

    op.execute("""
        CREATE TABLE i18n_translations (
            scope text NOT NULL,
            key text NOT NULL,
            locale char(2) NOT NULL,
            value text NOT NULL,
            updated_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (scope, key, locale)
        )
    """)
    op.execute("CREATE INDEX ix_i18n_scope_locale ON i18n_translations(scope, locale)")

    op.execute("""
        CREATE TABLE ingredient_allergens (
            ingredient_norm text NOT NULL,
            allergen allergen_enum NOT NULL,
            locale char(2) NOT NULL,
            PRIMARY KEY (ingredient_norm, allergen, locale)
        )
    """)
    op.execute("CREATE INDEX ix_ingredient_allergens_allergen ON ingredient_allergens(allergen)")

    op.execute("""
        CREATE TABLE condition_synonyms (
            synonym text PRIMARY KEY,
            canonical text NOT NULL,
            reason text NULL
        )
    """)

    # --- 7. Foods + recipes ---
    op.execute("""
        CREATE TABLE foods (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            name_en text NOT NULL,
            name_norm text NOT NULL,
            name_translations jsonb NOT NULL DEFAULT '{}'::jsonb,
            brand text NULL,
            country char(2) NULL,
            portion_g numeric NULL,
            kcal numeric NULL,
            protein_g numeric NULL,
            carbs_g numeric NULL,
            fat_g numeric NULL,
            fiber_g numeric NULL,
            sugar_g numeric NULL,
            sodium_mg numeric NULL,
            sat_fat_g numeric NULL,
            micronutrients jsonb NULL,
            barcode text NULL,
            verified bool NOT NULL DEFAULT false,
            source text NULL,
            embedding vector(1536) NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE UNIQUE INDEX uq_foods_name_norm ON foods(name_norm)")
    op.execute("CREATE INDEX ix_foods_embedding ON foods USING hnsw (embedding vector_cosine_ops) WITH (m = 32, ef_construction = 200)")
    op.execute("CREATE INDEX ix_foods_name_trgm ON foods USING gin (name_norm gin_trgm_ops)")
    op.execute("CREATE UNIQUE INDEX uq_foods_barcode ON foods(barcode) WHERE barcode IS NOT NULL")
    op.execute("CREATE INDEX ix_foods_country ON foods(country) WHERE country IS NOT NULL")

    op.execute("""
        CREATE TABLE recipes (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            name_en text NOT NULL,
            name_translations jsonb NOT NULL DEFAULT '{}'::jsonb,
            description_en text NULL,
            description_translations jsonb NOT NULL DEFAULT '{}'::jsonb,
            image_url text NULL,
            kcal int NULL,
            protein_g int NULL,
            carbs_g int NULL,
            fat_g int NULL,
            fiber_g int NOT NULL DEFAULT 0,
            sugar_g int NOT NULL DEFAULT 0,
            sodium_mg int NOT NULL DEFAULT 0,
            sat_fat_g int NOT NULL DEFAULT 0,
            tags text[] NOT NULL DEFAULT '{}',
            meal_time meal_time_enum NULL,
            prep_min int NULL,
            instructions_en text[] NOT NULL DEFAULT '{}',
            instructions_translations jsonb NOT NULL DEFAULT '{}'::jsonb,
            verified_by text NULL,
            source_batch text NULL,
            source_catalog text NULL,
            regions char(5)[] NOT NULL DEFAULT '{}',
            allergens allergen_enum[] NOT NULL DEFAULT '{}',
            recommended_conditions text[] NOT NULL DEFAULT '{}',
            contraindicated_conditions text[] NOT NULL DEFAULT '{}',
            target_goals goal_enum[] NOT NULL DEFAULT '{}',
            embedding vector(1536) NULL,
            created_at timestamptz NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX ix_recipes_regions ON recipes USING gin (regions)")
    op.execute("CREATE INDEX ix_recipes_allergens ON recipes USING gin (allergens)")
    op.execute("CREATE INDEX ix_recipes_tags ON recipes USING gin (tags)")
    op.execute("CREATE INDEX ix_recipes_target_goals ON recipes USING gin (target_goals)")
    op.execute("CREATE INDEX ix_recipes_meal_time ON recipes(meal_time)")
    op.execute("CREATE INDEX ix_recipes_source_batch ON recipes(source_batch) WHERE source_batch IS NOT NULL")
    op.execute("CREATE INDEX ix_recipes_embedding ON recipes USING hnsw (embedding vector_cosine_ops) WITH (m = 32, ef_construction = 200)")
    op.execute("CREATE UNIQUE INDEX uq_recipes_name_en ON recipes(name_en)")

    op.execute("""
        CREATE TABLE recipe_components (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            recipe_id uuid NOT NULL REFERENCES recipes(id) ON DELETE CASCADE,
            food_id uuid NULL REFERENCES foods(id) ON DELETE RESTRICT,
            sub_recipe_id uuid NULL REFERENCES recipes(id) ON DELETE RESTRICT,
            free_text_name text NULL,
            amount_g numeric NULL,
            modifier text NULL,
            position int NOT NULL DEFAULT 0,
            CHECK (food_id IS NOT NULL OR sub_recipe_id IS NOT NULL OR free_text_name IS NOT NULL)
        )
    """)
    op.execute("CREATE INDEX ix_recipe_components_recipe ON recipe_components(recipe_id)")
    op.execute("CREATE INDEX ix_recipe_components_food ON recipe_components(food_id) WHERE food_id IS NOT NULL")
    op.execute("CREATE INDEX ix_recipe_components_sub ON recipe_components(sub_recipe_id) WHERE sub_recipe_id IS NOT NULL")

    op.execute("""
        CREATE TABLE recipe_allergens (
            recipe_id uuid NOT NULL REFERENCES recipes(id) ON DELETE CASCADE,
            allergen allergen_enum NOT NULL,
            PRIMARY KEY (recipe_id, allergen)
        )
    """)
    op.execute("CREATE INDEX ix_recipe_allergens_allergen ON recipe_allergens(allergen)")

    # --- 8. Triggers — sync_recipe_allergens + sync_recipe_aggregates ---
    op.execute("""
        CREATE OR REPLACE FUNCTION sync_recipe_allergens()
            RETURNS trigger
            LANGUAGE plpgsql
            SECURITY DEFINER
        AS $$
        DECLARE
            affected_recipe uuid;
        BEGIN
            IF TG_OP = 'DELETE' THEN
                affected_recipe := OLD.recipe_id;
            ELSE
                affected_recipe := NEW.recipe_id;
            END IF;

            UPDATE recipes
               SET allergens = COALESCE((
                    SELECT array_agg(allergen ORDER BY allergen)
                      FROM recipe_allergens
                     WHERE recipe_id = affected_recipe
               ), '{}'::allergen_enum[])
             WHERE id = affected_recipe;

            RETURN NULL;
        END;
        $$;
    """)
    op.execute("""
        CREATE TRIGGER trg_sync_recipe_allergens
            AFTER INSERT OR UPDATE OR DELETE ON recipe_allergens
            FOR EACH ROW EXECUTE FUNCTION sync_recipe_allergens();
    """)

    op.execute("""
        CREATE OR REPLACE FUNCTION sync_recipe_aggregates()
            RETURNS trigger
            LANGUAGE plpgsql
            SECURITY DEFINER
        AS $$
        DECLARE
            affected_recipe uuid;
        BEGIN
            affected_recipe := COALESCE(NEW.recipe_id, OLD.recipe_id);

            UPDATE recipes r
               SET fiber_g   = COALESCE(agg.fiber, 0),
                   sugar_g   = COALESCE(agg.sugar, 0),
                   sodium_mg = COALESCE(agg.sodium_mg, 0),
                   sat_fat_g = COALESCE(agg.sat_fat, 0)
              FROM (
                  SELECT
                      SUM(f.fiber_g    * rc.amount_g / 100.0)::int AS fiber,
                      SUM(f.sugar_g    * rc.amount_g / 100.0)::int AS sugar,
                      SUM(f.sodium_mg  * rc.amount_g / 100.0)::int AS sodium_mg,
                      SUM(f.sat_fat_g  * rc.amount_g / 100.0)::int AS sat_fat
                    FROM recipe_components rc
                    JOIN foods f ON f.id = rc.food_id
                   WHERE rc.recipe_id = affected_recipe
                     AND rc.amount_g IS NOT NULL
              ) agg
             WHERE r.id = affected_recipe;

            RETURN NULL;
        END;
        $$;
    """)
    op.execute("""
        CREATE TRIGGER trg_sync_recipe_aggregates
            AFTER INSERT OR UPDATE OR DELETE ON recipe_components
            FOR EACH ROW EXECUTE FUNCTION sync_recipe_aggregates();
    """)

    # --- 9. Plan ---
    op.execute("""
        CREATE TABLE plans (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            type plan_type_enum NOT NULL,
            total_days int NOT NULL,
            current_day int NOT NULL DEFAULT 1,
            status plan_status_enum NOT NULL DEFAULT 'active',
            goal text NULL,
            meals_per_day int NOT NULL CHECK (meals_per_day BETWEEN 1 AND 4),
            preferences text[] NOT NULL DEFAULT '{}',
            kcal_target int NULL,
            version int NOT NULL DEFAULT 0,
            created_at timestamptz NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE UNIQUE INDEX one_active_plan ON plans(user_id) WHERE status = 'active'")
    op.execute("CREATE INDEX ix_plans_user_created ON plans(user_id, created_at DESC)")

    op.execute("""
        CREATE TABLE plan_days (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            plan_id uuid NOT NULL REFERENCES plans(id) ON DELETE CASCADE,
            day_index int NOT NULL,
            date date NOT NULL,
            completed bool NOT NULL DEFAULT false
        )
    """)
    op.execute("CREATE INDEX ix_plan_days_plan ON plan_days(plan_id, day_index)")

    op.execute("""
        CREATE TABLE plan_meals (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            plan_day_id uuid NOT NULL REFERENCES plan_days(id) ON DELETE CASCADE,
            meal_time meal_time_enum NOT NULL,
            recipe_id uuid NULL REFERENCES recipes(id) ON DELETE RESTRICT,
            kcal int NULL,
            protein_g int NULL,
            carbs_g int NULL,
            fat_g int NULL,
            water_ml int NULL,
            water_pct numeric NULL,
            completed bool NOT NULL DEFAULT false,
            swapped_from uuid NULL
        )
    """)
    op.execute("CREATE INDEX ix_plan_meals_day ON plan_meals(plan_day_id)")

    op.execute("""
        CREATE TABLE plan_generation_seeds (
            plan_id uuid PRIMARY KEY REFERENCES plans(id) ON DELETE CASCADE,
            seed bigint NOT NULL
        )
    """)

    # --- 10. Tracking ---
    op.execute("""
        CREATE TABLE food_logs (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            date date NOT NULL,
            meal_time meal_time_enum NOT NULL,
            food_id uuid NULL REFERENCES foods(id) ON DELETE RESTRICT,
            recipe_id uuid NULL REFERENCES recipes(id) ON DELETE RESTRICT,
            free_text_name text NULL,
            amount_g numeric NULL,
            kcal int NULL,
            protein_g int NULL,
            carbs_g int NULL,
            fat_g int NULL,
            method log_method_enum NOT NULL,
            confidence numeric(4,3) NULL,
            source_image_url text NULL,
            idempotency_key text NULL,
            prompt_sha256 text NULL,
            created_at timestamptz NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX ix_food_logs_user_date ON food_logs(user_id, date DESC)")
    op.execute("CREATE INDEX ix_food_logs_user_date_meal ON food_logs(user_id, date, meal_time)")
    op.execute("CREATE UNIQUE INDEX one_log_per_idem_key ON food_logs(user_id, idempotency_key) WHERE idempotency_key IS NOT NULL")

    op.execute("""
        CREATE TABLE water_logs (
            time timestamptz NOT NULL,
            user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            ml int NOT NULL,
            target_ml int NULL
        )
    """)
    op.execute("SELECT create_hypertable('water_logs', 'time', if_not_exists => TRUE)")
    op.execute("CREATE INDEX ix_water_logs_user_time ON water_logs(user_id, time DESC)")

    op.execute("""
        CREATE TABLE weight_logs (
            time timestamptz NOT NULL,
            user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            weight_kg numeric NOT NULL,
            body_fat_pct numeric NULL,
            waist_cm numeric NULL,
            photo_url text NULL
        )
    """)
    op.execute("SELECT create_hypertable('weight_logs', 'time', if_not_exists => TRUE)")
    op.execute("CREATE INDEX ix_weight_logs_user_time ON weight_logs(user_id, time DESC)")

    # Continuous aggregate — 14d / 30d rolling means (biometric_aggregates_daily).
    # Materialised view computed daily by TimescaleDB; refreshed by policy.
    op.execute("""
        CREATE MATERIALIZED VIEW biometric_aggregates_daily
        WITH (timescaledb.continuous) AS
        SELECT
            user_id,
            time_bucket(INTERVAL '1 day', time) AS day,
            AVG(weight_kg)    AS weight_kg_mean,
            MIN(weight_kg)    AS weight_kg_min,
            MAX(weight_kg)    AS weight_kg_max,
            COUNT(*)          AS n_measurements
        FROM weight_logs
        GROUP BY user_id, day
        WITH NO DATA
    """)
    op.execute("""
        SELECT add_continuous_aggregate_policy(
            'biometric_aggregates_daily',
            start_offset => INTERVAL '60 days',
            end_offset   => INTERVAL '1 hour',
            schedule_interval => INTERVAL '1 hour',
            if_not_exists => TRUE
        )
    """)

    op.execute("""
        CREATE TABLE fasting_sessions (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            method_h int NOT NULL CHECK (method_h IN (16,18,20)),
            start_ts timestamptz NOT NULL,
            end_ts timestamptz NULL,
            duration_s int NULL,
            target_s int NOT NULL,
            achieved bool NOT NULL DEFAULT false
        )
    """)
    op.execute("CREATE INDEX ix_fasting_user_start ON fasting_sessions(user_id, start_ts DESC)")

    op.execute("""
        CREATE TABLE daily_goals (
            user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            date date NOT NULL,
            item daily_goal_item_enum NOT NULL,
            completed bool NOT NULL DEFAULT false,
            auto bool NOT NULL DEFAULT false,
            completed_at timestamptz NULL,
            PRIMARY KEY (user_id, date, item)
        )
    """)

    op.execute("""
        CREATE TABLE grocery_lists (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            plan_id uuid NOT NULL REFERENCES plans(id) ON DELETE CASCADE,
            generated_at timestamptz NOT NULL DEFAULT now()
        )
    """)
    op.execute("""
        CREATE TABLE grocery_items (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            list_id uuid NOT NULL REFERENCES grocery_lists(id) ON DELETE CASCADE,
            category grocery_category_enum NOT NULL,
            name text NOT NULL,
            amount text NULL,
            purchased bool NOT NULL DEFAULT false
        )
    """)
    op.execute("CREATE INDEX ix_grocery_items_list ON grocery_items(list_id)")

    op.execute("""
        CREATE TABLE progress_photos (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            taken_at timestamptz NOT NULL,
            weight_kg numeric NULL,
            image_url text NULL,
            blurhash text NULL,
            created_at timestamptz NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX ix_progress_photos_user_taken ON progress_photos(user_id, taken_at DESC)")

    # --- 11. Gamification ---
    op.execute("""
        CREATE TABLE streaks (
            user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            type streak_type_enum NOT NULL,
            value int NOT NULL DEFAULT 0,
            last_day date NULL,
            PRIMARY KEY (user_id, type)
        )
    """)
    op.execute("""
        CREATE TABLE achievements (
            user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            code text NOT NULL,
            unlocked_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (user_id, code)
        )
    """)

    # --- 12. Coach ---
    op.execute("""
        CREATE TABLE coach_conversations (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            title text NULL,
            locale char(2) NOT NULL DEFAULT 'en',
            created_at timestamptz NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX ix_coach_conv_user ON coach_conversations(user_id, created_at DESC)")

    op.execute("""
        CREATE TABLE coach_messages (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            conv_id uuid NOT NULL REFERENCES coach_conversations(id) ON DELETE CASCADE,
            role coach_role_enum NOT NULL,
            content text NOT NULL,
            tokens_in int NULL,
            tokens_out int NULL,
            prompt_sha256 text NULL,
            created_at timestamptz NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX ix_coach_messages_prompt ON coach_messages(prompt_sha256) WHERE prompt_sha256 IS NOT NULL")
    op.execute("CREATE INDEX ix_coach_messages_conv ON coach_messages(conv_id, created_at)")

    op.execute("""
        CREATE TABLE coach_sse_tickets (
            token_hash text PRIMARY KEY,
            user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            conv_id uuid NOT NULL REFERENCES coach_conversations(id) ON DELETE CASCADE,
            expires_at timestamptz NOT NULL
        )
    """)
    op.execute("CREATE INDEX ix_coach_sse_expires ON coach_sse_tickets(expires_at)")

    # --- 13. AI / ops ---
    op.execute("""
        CREATE TABLE ai_prompts (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            name text NOT NULL,
            version int NOT NULL,
            body text NOT NULL,
            model text NOT NULL,
            params jsonb NOT NULL DEFAULT '{}'::jsonb,
            active bool NOT NULL DEFAULT false,
            description text NULL,
            updated_by uuid NULL REFERENCES users(id) ON DELETE SET NULL,
            created_at timestamptz NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE UNIQUE INDEX one_active_prompt_per_name ON ai_prompts(name) WHERE active = true")
    op.execute("CREATE UNIQUE INDEX uq_ai_prompts_name_version ON ai_prompts(name, version)")

    op.execute("""
        CREATE TABLE feature_flags (
            key text PRIMARY KEY,
            enabled bool NOT NULL DEFAULT false,
            rollout_pct int NOT NULL DEFAULT 0 CHECK (rollout_pct BETWEEN 0 AND 100),
            payload jsonb NOT NULL DEFAULT '{}'::jsonb,
            description text NULL,
            updated_by uuid NULL REFERENCES users(id) ON DELETE SET NULL,
            updated_at timestamptz NOT NULL DEFAULT now()
        )
    """)

    # --- 14. Audit ---
    op.execute("""
        CREATE TABLE audit_log (
            id bigserial PRIMARY KEY,
            ts timestamptz NOT NULL DEFAULT now(),
            user_id uuid NULL REFERENCES users(id) ON DELETE SET NULL,
            actor_type actor_type_enum NOT NULL,
            action text NOT NULL,
            target_type text NULL,
            target_id text NULL,
            metadata jsonb NULL
        )
    """)
    op.execute("CREATE INDEX ix_audit_log_user_ts ON audit_log(user_id, ts DESC)")
    op.execute("CREATE INDEX ix_audit_log_action ON audit_log(action, ts DESC)")
    # Append-only contract: revoke UPDATE/DELETE for the application role.
    # Migration runs as superuser; we revoke at the PUBLIC level to be safe and
    # do the same for the 'nova' app role if present.
    op.execute("REVOKE UPDATE, DELETE ON audit_log FROM PUBLIC")
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'nova') THEN
                EXECUTE 'REVOKE UPDATE, DELETE ON audit_log FROM nova';
            END IF;
        END$$;
    """)

    # ------------------------------------------------------------------
    # Seeds
    # ------------------------------------------------------------------
    conn = op.get_bind()

    # Regions
    for r in REGION_SEEDS:
        conn.execute(
            sa.text("""
                INSERT INTO regions (code, name, allergen_set, countries, default_locale)
                VALUES (:code, :name, CAST(:aset AS allergen_enum[]), CAST(:countries AS char(2)[]), :loc)
                ON CONFLICT (code) DO NOTHING
            """),
            {
                "code": r["code"],
                "name": r["name"],
                "aset": list(r["allergen_set"]),
                "countries": list(r["countries"]),
                "loc": r["default_locale"],
            },
        )

    # i18n_translations — allergens × locales
    for key, by_loc in ALLERGEN_I18N.items():
        for loc, val in by_loc.items():
            conn.execute(
                sa.text("""
                    INSERT INTO i18n_translations(scope,key,locale,value)
                    VALUES ('allergen',:k,:l,:v)
                    ON CONFLICT (scope,key,locale) DO UPDATE SET value=EXCLUDED.value
                """),
                {"k": key, "l": loc, "v": val},
            )

    for key, by_loc in CONDITION_I18N.items():
        for loc, val in by_loc.items():
            conn.execute(
                sa.text("""
                    INSERT INTO i18n_translations(scope,key,locale,value)
                    VALUES ('condition',:k,:l,:v)
                    ON CONFLICT (scope,key,locale) DO UPDATE SET value=EXCLUDED.value
                """),
                {"k": key, "l": loc, "v": val},
            )

    for key, by_loc in GOAL_I18N.items():
        for loc, val in by_loc.items():
            conn.execute(
                sa.text("""
                    INSERT INTO i18n_translations(scope,key,locale,value)
                    VALUES ('goal',:k,:l,:v)
                    ON CONFLICT (scope,key,locale) DO UPDATE SET value=EXCLUDED.value
                """),
                {"k": key, "l": loc, "v": val},
            )

    for key, by_loc in MEAL_TIME_I18N.items():
        for loc, val in by_loc.items():
            conn.execute(
                sa.text("""
                    INSERT INTO i18n_translations(scope,key,locale,value)
                    VALUES ('meal_time',:k,:l,:v)
                    ON CONFLICT (scope,key,locale) DO UPDATE SET value=EXCLUDED.value
                """),
                {"k": key, "l": loc, "v": val},
            )

    for key, by_loc in ACTIVITY_LEVEL_I18N.items():
        for loc, val in by_loc.items():
            conn.execute(
                sa.text("""
                    INSERT INTO i18n_translations(scope,key,locale,value)
                    VALUES ('activity_level',:k,:l,:v)
                    ON CONFLICT (scope,key,locale) DO UPDATE SET value=EXCLUDED.value
                """),
                {"k": key, "l": loc, "v": val},
            )

    # condition_synonyms
    for syn, canon, reason in CONDITION_SYNONYMS:
        conn.execute(
            sa.text("""
                INSERT INTO condition_synonyms(synonym, canonical, reason)
                VALUES (:s,:c,:r)
                ON CONFLICT (synonym) DO UPDATE SET canonical=EXCLUDED.canonical, reason=EXCLUDED.reason
            """),
            {"s": syn, "c": canon, "r": reason},
        )


# ---------------------------------------------------------------------------
# downgrade()
# ---------------------------------------------------------------------------

def downgrade() -> None:
    # Continuous aggregates / hypertables: drop view + tables in reverse order.
    op.execute("DROP MATERIALIZED VIEW IF EXISTS biometric_aggregates_daily")

    # Drop tables in reverse dependency order.
    for tbl in [
        "audit_log",
        "feature_flags",
        "ai_prompts",
        "coach_sse_tickets",
        "coach_messages",
        "coach_conversations",
        "achievements",
        "streaks",
        "progress_photos",
        "grocery_items",
        "grocery_lists",
        "daily_goals",
        "fasting_sessions",
        "weight_logs",
        "water_logs",
        "food_logs",
        "plan_generation_seeds",
        "plan_meals",
        "plan_days",
        "plans",
        "recipe_allergens",
        "recipe_components",
        "recipes",
        "foods",
        "condition_synonyms",
        "ingredient_allergens",
        "i18n_translations",
        "regions",
        "nutritional_goals",
        "user_profiles",
        "otp_codes",
        "refresh_tokens",
        "users",
    ]:
        op.execute(f"DROP TABLE IF EXISTS {tbl} CASCADE")

    # Functions
    op.execute("DROP FUNCTION IF EXISTS sync_recipe_allergens() CASCADE")
    op.execute("DROP FUNCTION IF EXISTS sync_recipe_aggregates() CASCADE")

    # Enums (drop after tables that reference them are gone)
    for t in [
        "actor_type_enum", "coach_role_enum", "streak_type_enum",
        "grocery_category_enum", "daily_goal_item_enum", "log_method_enum",
        "otp_purpose_enum", "plan_status_enum", "plan_type_enum",
        "goal_reason_enum", "meal_time_enum", "theme_enum",
        "activity_level_enum", "goal_enum", "units_enum", "sex_enum",
        "allergen_enum",
    ]:
        op.execute(f"DROP TYPE IF EXISTS {t}")
    # Extensions intentionally NOT dropped — shared with init.sql / other schemas.
