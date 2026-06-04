# ADR-0017 — Legal scope statement: nutrition planning only

**Status:** Accepted
**Date:** 2026-06-01

## Scope statement

**NOVA Nutrition is a nutrition planning application.** It adapts meal plans to the user's self-declared biometrics, goals, dietary pattern, and medical conditions.

**NOVA does NOT:**
- Diagnose medical conditions
- Prescribe medications, supplements, vitamins, or pills
- Provide nutrition guidance
- Replace consultation with a qualified medical professional
- Generate custom recipes per individual prescription

**NOVA DOES:**
- Filter recipes against declared allergens and contraindicated conditions (Layer 1 SQL safety floor)
- Compute daily kcal + macro targets via established formulas (Mifflin-St Jeor, Cunningham, IOM DRI energy surplus)
- Rank recipes by user preference, variety, and dietary pattern
- Maintain immutable plan history for user transparency

## Operational guarantees

### Catalog (33,758 recipes, audited 2026-06-01)
- 0 supplement ingredients (whey, casein, BCAA, creatine, pre-workout, mass gainer, protein powder, multivitamins)
- 0 drug name references
- 0 pill/tablet/capsule references
- 0 dosage units (X mg / X UI of vitamin or supplement)
- 0 medical claims (cura/trata/previene/cardioprotector/antiinflamatorio/detox)
- 0 prescription language (receta médica, posología, prescripción)

### Coach LLM (system prompt enforced)
> "Eres NOVA Coach: nutrición práctica, breve, en el idioma del usuario. Nunca des diagnóstico médico ni prescribas medicamentos."

Hard refuse layers (zero-cost, pre-LLM):
- `MEDICAL_REDIRECT` intent classifier — detects medication / drug / dose keywords → template response redirecting to doctor
- `OFFTOPIC` refuse — queries unrelated to nutrition → fixed template
- `PROMPT_INJECTION` refuse — attempts to alter system prompt → fixed template

### Algorithm (`app/plan/`)
- No "prescribed" semantics — docstring updated to "computed"
- BMR / TDEE / macros are mathematical calculations, not medical recommendations
- Safety floor (Layer 1 contraindicated_conditions array exclusion + condition-specific gates) prevents serving recipes that would harm declared-condition users

## Disclaimer placement

Mobile clients must show:

### Signup screen (before form fields)
> NOVA es un planificador nutricional. No reemplaza consulta médica.
> Si tienes una condición médica, consulta a tu doctor antes de seguir tu plan.
> [ ✓ Entiendo y acepto ]

### Per-plan footer (visible always in plan view)
> ℹ️ Plan informativo, no consejo médico. Consulta a tu médico ante dudas.

### App Store / Play Store metadata
"NOVA is a nutrition planning app. Not intended for medical diagnosis or treatment. Consult your healthcare provider for medical decisions."

## Liability framing

NOVA does not opt out of liability — it operates within a clearly stated scope:
1. **Safety floor first** — user's declared condition triggers strict catalog filtering. Diabetic users never see high-sugar recipes. CKD users never see high-K recipes. Pregnant users only see `pregnancy_safe = true` items.
2. **Disclaimer second** — explicit non-medical scope statement on every surface.
3. **Refuse-on-uncertainty** — free-text allergens refuse plan generation (ADR-0014).
4. **Audit trail third** — `plan_versions` immutable history. Compliance can replay any plan from `algorithm_version + variant_id + weights_checksum + inputs_hash`.

## Consequences

- Mobile team has clear UI mandate (signup disclaimer + per-plan footer + store metadata).
- Marketing / sales must not represent NOVA as a nutrition or diagnostic tool.
- Customer support trained to redirect medical questions to professional consult.
- Future features (recalibration, plateau detection) inherit this scope by default — algorithm choices, not prescriptions.

## References

- ADR-0014 allergen freetext refuse policy
- `app/coach/application/chat_message.py::SYSTEM_PROMPT`
- `app/coach/infrastructure/intent_classifier.py::MEDICAL_PATTERNS`
- `docs/mobile/ONBOARDING_API_CONTRACT.md` §6.2 disclaimer placement
- Catalog scope verification: `scripts/catalog_legal_cleanup_2026_06_01.py`
