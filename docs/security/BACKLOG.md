# Security Backlog

**Status:** Sprints S0 + S1-quick COMPLETE. Rest deferred with explicit triggers.
**Last updated:** 2026-06-01
**Rule:** OSS-only. No paid plugins. Free tier max-out.

---

## ✅ Sprint S0 — pre-launch hardening (shipped)

S0-A security headers + CORS + /docs gate
S0-B BOLA assert_owns
S0-C Pydantic extra=forbid (10 schemas)
S0-D JWT revocation Redis denylist
S0-E SECURITY.md + VDP
S0-F anti-sniff Proxyman/Charles/Burp
S0-H pgvector tenancy audit + regression guard
S0-I SSRF guard outbound httpx
S0-J JWT key rotation kid header
S0-K per-IP global rate-limit

Deferred from S0:
- Cloudflare Turnstile signup — defer until CF domain configured.

---

## ✅ Sprint S1-quick — high-ROI dev-time defenses (shipped)

S1-1 CI security scans (bandit + semgrep + gitleaks + pip-audit + trivy + dependabot)
S1-2 RBAC matrix (Role enum + require_role dep + docs)
S1-3 MIME sniff verification vision uploads (magic bytes, no libmagic dep)
S1-4 anomaly guard tracking weight (physiological bounds + delta)

---

## ⏸️ Sprint S1 — remaining items (deferred)

| Item | Esfuerzo | Trigger to activate |
|------|----------|---------------------|
| Data classification matrix | 2h | Pre-launch legal review OR first DSAR |
| Data retention cron (food_logs/vision_jobs purge) | 4h | DB > 5GB OR 90d post-launch |
| HSTS preload submit (hstspreload.org) | 30min | Domain stable 30d (manual submit by owner) |
| Privacy Policy + ToS templates | 4h | Pre-launch lawyer review |
| Cookie consent banner spec | 2h | EU launch confirmed |

---

## ⏸️ Sprint S2 — defense in depth (deferred)

| Item | Esfuerzo | Trigger to activate |
|------|----------|---------------------|
| pgcrypto field-level encryption (conditions, allergens) | 8h | First B2B customer demand OR PII regulator inquiry |
| MFA TOTP (account delete + payment method change) | 6h | First fraud incident OR 1k paying users |
| OWASP ZAP baseline en CI | 4h | After API surface stabilises (>30 endpoints maturing) |
| SOPS + age secrets (envar Dokploy → gitops) | 6h | Team ≥2 members |
| Loki + Promtail self-hosted SIEM | 4h | Sentry free tier exhausted |
| ROPA — Record of Processing Activities | 6h | GDPR DSAR received OR EU large-scale processing |
| DPIA-lite (data protection impact assessment) | 4h | Same as ROPA |
| App attestation hooks (Apple App Attest / Play Integrity) | 6h | Mobile app published to stores |

**NOT in backlog (paid / external action — declined per owner policy):**
- Pen-test externo (~$1.5k) — defer until $5k MRR + funding

---

## ⏸️ Sprint S3 — maturity / compliance (deferred)

| Item | Esfuerzo | Trigger to activate |
|------|----------|---------------------|
| WAL archiving PITR | 4h | 1k DAU OR first data-loss incident |
| Disaster Recovery drill | 4h | First production data + Q+1 |
| Access review log + cron | 3h | Team ≥3 members |
| Threat model formal STRIDE (identity/billing/vision/coach) | 8h | Pre-Series A OR enterprise audit |
| Incident Response runbook | 4h | First incident OR pre-launch hard date |
| Vulnerability tracking (CVD program enhancement) | 3h | First VDP report received |
| Compliance audit prep | 4h | ISO certification ambition declared |

**NOT in backlog (paid / declined):**
- Backup encryption + off-site (B2/Hetzner ~$1-5/mo) — declined per owner; Hostinger weekly only.

---

## Compensating controls active right now

Layer 1 (edge):
- Cloudflare DDoS + edge filtering (free tier)
- Traefik HTTPS Let's Encrypt auto

Layer 2 (middleware, in code):
- AntiSniffMiddleware (S0-F) — MITM tool detection
- IpRateLimitMiddleware (S0-K) — volumetric cap
- SecurityHeadersMiddleware (S0-A) — HSTS/CSP/Frame/Referrer/Permissions
- CORSMiddleware (S0-A) — explicit origins

Layer 3 (auth):
- PyJWT RS256 + Argon2id
- JWT kid rotation (S0-J)
- JWT denylist Redis (S0-D)
- BOLA assert_owns (S0-B)
- RBAC require_role (S1-2)
- Pydantic extra=forbid (S0-C)

Layer 4 (input):
- MIME sniff vision (S1-3)
- Anomaly guard tracking (S1-4)
- Idempotency Redis+DB

Layer 5 (outbound):
- SSRF guard safe_async_client (S0-I)
- Cost cap OpenAI ($1.50/user/day + kill switch)
- Circuit breakers (OpenAI / Stripe / MP)

Layer 6 (observability):
- Sentry + PII scrubber
- Prometheus metrics + alerts
- Structured logs (structlog)

Layer 7 (CI/CD — S1-1):
- bandit + semgrep SAST
- gitleaks secret scan
- pip-audit dep CVE
- trivy fs + config scan
- dependabot weekly bumps

Layer 8 (process):
- SECURITY.md + VDP (S0-E)
- RBAC.md (S1-2)
- pgvector-tenancy.md (S0-H)
- Conventional commits + atomic PRs
- BOLA regression tests
- pgvector tenancy regression test

Layer 9 (LLM):
- Coach guardrails (medical + offtopic + injection)
- Vision confidence threshold + low-conf confirm endpoint
- Cost cap per-user / per-org

---

## Reminder for next assistant

Only activate backlog item if its trigger has fired. Do NOT auto-implement.
1. Notify owner: "Trigger X fired, item Y due."
2. Estimate work + propose implementation plan.
3. Wait for owner confirmation.
4. Use OSS-only tools. No paid plugins.
