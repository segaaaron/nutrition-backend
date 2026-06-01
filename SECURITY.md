# Security Policy

## Supported Versions

Only the latest `main` branch receives security updates. NOVA Nutrition is in
active development pre-launch; pinned versions are not maintained.

| Version | Supported |
| ------- | --------- |
| main    | ✅        |
| < main  | ❌        |

## Reporting a Vulnerability

**Please do NOT open public GitHub issues for security vulnerabilities.**

Email: **security@nova-nutrition.com** (PGP key available on request).

Include:
- Affected endpoint or component
- Reproduction steps (minimal proof-of-concept)
- Impact assessment
- Suggested mitigation (optional)

### What to expect

| Stage | SLA |
|-------|-----|
| Initial acknowledgement | 72 hours |
| Triage + severity assigned | 7 days |
| Fix timeline communicated | 14 days |
| Critical fix deployed | 30 days max |
| Public disclosure (coordinated) | 90 days after fix |

### Scope

In-scope:
- `*.nova-nutrition.com` API endpoints
- Authentication / authorization flows
- Payment webhook integrity (Stripe, MercadoPago)
- Data exposure (PII, health data, billing)
- Prompt injection / LLM scope evasion
- Rate-limit / cost-cap bypass

Out-of-scope:
- Denial of service via volumetric attacks (handled by Cloudflare)
- Theoretical issues without reproducible PoC
- Issues requiring physical access or social engineering
- Vulnerabilities in third-party dependencies already disclosed upstream
- Self-XSS, content spoofing without security impact
- Missing security headers without demonstrable exploit

## Hall of Fame

Researchers who report valid security issues receive public acknowledgement
(opt-in) in `docs/security/HALL_OF_FAME.md` after coordinated disclosure.

## Safe Harbour

Good-faith security research conducted in scope is authorised. We will not
pursue legal action against researchers who:
- Avoid privacy violations, data destruction, and service degradation
- Stop testing upon discovery of a vulnerability
- Disclose privately and allow reasonable time to fix

## Standards

This project aligns with:
- **OWASP API Security Top 10 (2023)**
- **OWASP ASVS Level 2**
- **ISO/IEC 27001:2022 Annex A** (subset applicable to single-dev SaaS)
- **ISO/IEC 27018** (PII processor controls)
- **GDPR, LGPD, CCPA, Ley 29733 (PE), Ley 25.326 (AR)**

Full plan: `docs/security/PLAN.md`.
