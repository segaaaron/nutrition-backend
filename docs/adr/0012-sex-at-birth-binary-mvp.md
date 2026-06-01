# ADR-0012 — sex_at_birth binary MVP + internal rename

**Status:** Accepted
**Date:** 2026-06-01

## Decision

For MVP, the `sex` field captured by mobile onboarding is treated as **`sex_at_birth: Literal["male","female"]`** at the algorithm layer. UI labels remain "Sexo / Sex". JSON wire field name stays `sex` for v1 backward compatibility.

## Why binary

Mifflin-St Jeor BMR formula is driven by sex assigned at birth (lean mass + hormonal baseline). Non-binary identity does not change BMR. For an inclusive product, gender identity belongs in profile preferences post-onboarding; BMR math needs only the binary biological input.

## Helper text mandate (mobile)

UI must add helper text under the sex chips:
> "Para calcular tu metabolismo basal correctamente."

## Trans / non-binary inclusivity

- v1: `sex` binary, no separate gender field.
- v2 (future): add optional `gender_identity` profile field (informational, not consumed by algorithm).
- Trans users currently select their assigned-at-birth sex for accurate BMR; explicit UI text covers this without outing.

## Consequences

- Pre-existing `sex` field name unchanged (no wire-break for mobile).
- Internal rename happens via docstrings + ADR documentation only — code variable remains `sex`.
- Future `gender_identity` extension is additive, non-breaking.

## References

- `app/profile/presentation/schemas.py::OnboardingRequest.sex`
- `docs/mobile/ONBOARDING_API_CONTRACT.md` §2 helper text mandate
