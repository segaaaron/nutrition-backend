# Vulnerability Disclosure Policy (VDP)

**Version:** 1.0 · **Effective:** 2026-06-01 · **Owner:** Security Lead

## Purpose

NOVA Nutrition welcomes responsible security research. This policy defines how
security researchers can report vulnerabilities safely and what to expect from us.

## Scope

### In-scope assets
- `*.ms-tech-stack.cloud` (production API + future web)
- Mobile app binaries (iOS, Android — when published)
- Webhook endpoints (`/webhooks/stripe`, `/webhooks/mercadopago`)
- Public GitHub repositories under the `nova-nutrition` org

### Out-of-scope
- Third-party services (Stripe, MercadoPago, OpenAI, Cloudflare, Hostinger)
- Marketing site / blog (static, no user data)
- Issues in development branches (not deployed)
- Social engineering of staff
- Physical attacks on infrastructure

## Authorised activities

You MAY:
- Test endpoints with your own account
- Use automated scanners against scoped assets (rate-limit to <10 req/s)
- Decompile and analyse mobile binaries

You MUST NOT:
- Access data of other users (use test accounts only)
- Run destructive payloads (data deletion, modification of others' records)
- Exfiltrate more data than needed to prove vulnerability
- Use vulnerabilities for personal gain
- Disclose publicly before coordinated timeline

## Reporting

**Channel:** `security@ms-tech-stack.cloud`
**PGP:** Available on request

### Required information
1. Vulnerability type (e.g. BOLA, SQLi, RCE)
2. Affected endpoint(s) + method(s)
3. Steps to reproduce (one PoC, minimal)
4. Impact (what data/action exposed)
5. Suggested remediation (optional)

### Severity scoring
We use **CVSS 3.1** for severity. Approximate response SLA:

| Severity | CVSS | Acknowledge | Triage | Fix target |
|----------|------|-------------|--------|-----------|
| Critical | 9.0-10 | 24h | 48h | 7 days |
| High | 7.0-8.9 | 48h | 5 days | 30 days |
| Medium | 4.0-6.9 | 72h | 14 days | 90 days |
| Low | 0.1-3.9 | 7 days | 30 days | Next major release |

## Safe harbour

Activities consistent with this policy:
- Are considered authorised research
- Will not result in legal action by NOVA Nutrition
- Are exempt from any "anti-hacking" claim NOVA might otherwise pursue

If a third party initiates legal action, NOVA will make good-faith efforts to
inform the third party that you complied with this policy.

## Coordinated disclosure

We follow a **90-day disclosure window** from initial report, extensible by
mutual agreement. After fix deployment + 90 days, the researcher may publish
technical details. Earlier publication requires prior coordination.

## Recognition

With your permission, we acknowledge contributions in `docs/security/HALL_OF_FAME.md`.
We do NOT currently offer monetary bounties (pre-revenue startup); this may
change post-Series A.

## Updates

This policy is versioned. Material changes will be announced via GitHub.

---

*Aligned with ISO/IEC 29147:2018 (vulnerability disclosure) and ISO/IEC 30111:2019 (vulnerability handling processes).*
