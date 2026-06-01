# ADR-0014 — Allergen free-text refuse policy

**Status:** Accepted (shipped)
**Date:** 2026-06-01

## Decision

If `OnboardingRequest.other_allergy` is non-empty and non-whitespace, server **refuses plan generation** with `urn:nova:problem:plan:allergen-unmapped-requires-review` (HTTP 422). Mobile UI must show a support-redirect modal (see `docs/mobile/ONBOARDING_API_CONTRACT.md` §6.1).

## Why

Layer 1 SQL filter matches user allergies against the closed enum array `recipe.allergens[]`. A free-text allergen string never matches anything → recipes containing the actual allergen pass the filter → user with `"ajonjolí"` (sesame) silent-allergic receives sesame-containing recipes → anaphylaxis.

**Triple-cost outcomes:**
- FALCPA (US) strict liability
- EU 1169 declared-allergens violation
- App Store / Play Store removal for health-safety incident

**Single non-empty allergen free-text input is a catastrophic vector. Refuse-by-default is the only safe policy.**

## Server behaviour

```python
# app/profile/presentation/schemas.py
@model_validator(mode="after")
def _validate(self) -> "OnboardingRequest":
    if self.other_allergy and self.other_allergy.strip():
        raise ValueError("allergen_unmapped_requires_review")
    ...
```

Pydantic raises ValueError → FastAPI returns 422 + Problem Details payload.

## Mobile UX

Modal text (Spanish):
> ⚠️ Tu alergia personalizada requiere revisión manual.
> No podemos filtrar automáticamente alergias fuera de nuestra lista.
> [ Contactar soporte ] [ Quitar alergia personalizada ]

## Alternatives considered

1. **Best-effort NLP map** — rejected: false positives mean false safety. A user types "ajonjolí" → NLP guesses "sesame" with 0.7 confidence → still wrong 30% of the time = users still get exposed.
2. **Warn-only** — rejected: silent failure mode that produces broken UI behavior + still exposes user.
3. **Disable the "Otra alergia…" field on UI** — alternative considered; rejected because users WILL request unsupported allergens (sesame currently is supported, but lupin/celery/molluscs are in enum but maybe not in UI chip subset). Allowing free-text capture is fine; refusing plan-generation is the discipline.

## Consequences

- Mobile must implement refuse-modal flow.
- Support queue handles vocab-expansion review (manual triage).
- Vocabulary expansion requires future ADR + migration (closed enum is the source of truth).

## References

- ADR-0001 closed allergen vocabulary
- `app/profile/presentation/schemas.py::OnboardingRequest._validate`
- `tests/unit/profile/test_onboarding_schema.py::test_allergen_freetext_refuses`
