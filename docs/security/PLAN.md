# NOVA Nutrition — Security Plan (OWASP + ISO 27000 family)

**Owner:** Miguel Saravia (single dev) · **Status:** Living document · **Last review:** 2026-06-01
**Scope:** Backend API (FastAPI 0.115, Py 3.12), Postgres 16 + TimescaleDB-HA + pgvector, Redis 7, Arq workers, Dokploy/Traefik on Hostinger KVM, Cloudflare edge.
**Compliance surface:** GDPR (EU), LGPD (BR), CCPA (CA), Ley 29733 (PE), Ley 25.326 (AR). HIPAA out of scope.
**Related ADRs:** 0001 (vocab), 0004 (cost cap), 0005 (erasure), 0006 (models), 0008 (multi-region).

---

## 0. Executive Posture

| Pillar | State | Target post-S1 |
|---|---|---|
| AuthN/AuthZ | Strong (JWT RS256, Argon2, OAuth, OTP) | + key rotation, + RBAC matrix |
| Transport | Strong (TLS via Traefik+LE, CF edge) | + HSTS preload, + cert pinning N/A |
| Data at rest | Weak (host-managed) | + pgcrypto field-level for PHI, + encrypted backups |
| Secrets | Dokploy env vars (current) — rotation manual per CVE alert | 90-day rotation policy (DEFERRED until team ≥2) |
| Logging/SIEM | structlog stdout + local ErrorTracker (ring buffer + JSONL) (sufficient for closed-beta) | Loki/Promtail DEFERRED (>1M log lines/day trigger) |
| AppSec CI | Active | ruff S-rules (lint) + GitHub native (Secret scanning, Push Protection, Code Scanning CodeQL, Dependabot security advisories) — no custom security.yml, no custom dependabot.yml |
| IR / DR | Absent | + runbook + PITR test quarterly |
| Compliance docs | Partial | + ROPA, DPIA-lite, privacy policy, VDP |

**Verdict pre-launch:** GO conditional on completing **Sprint S0** items below. Current baseline is above LatAm SaaS median but below ISO 27001 audit threshold (expected for solo-dev MVP).

---

## 1. OWASP API Security Top 10 (2023)

| # | Risk | State | NOVA-specific surface | Mitigation (files) | Prio |
|---|---|---|---|---|---|
| API1 | BOLA (Broken Object Level Auth) | ⚠️ partial | `/v1/tracking/logs/{id}`, `/v1/plan/{id}`, `/v1/recipes/{id}` — must verify `user_id == jwt.sub` | Add `@require_owner` dep across all `app/*/api/routers.py`; integration tests per context | **P0** |
| API2 | Broken Authentication | ✅ strong | JWT RS256, Argon2id, OAuth Google/Apple, OTP email | Add JWT key rotation (kid header) `app/core/security.py`; OTP rate-limit per-email already via Redis | P1 |
| API3 | BOPLA (Property-level) | ⚠️ partial | `PATCH /v1/profile` — must allow only whitelist fields; risk: client sets `is_premium=true` | Pydantic `model_config = ConfigDict(extra='forbid')` audit on every `*Update` schema | **P0** |
| API4 | Unrestricted Resource Consumption | ⚠️ partial | Vision endpoint (OpenAI cost), coach LLM, embeddings | Cost cap ADR-0004 ✅; add per-IP global rate-limit at Traefik middleware; payload max 5MB | P1 |
| API5 | Broken Function Level Auth | ⚠️ partial | Admin endpoints (none yet) + future `/admin/*` | Define RBAC enum `{user, premium, support, admin}` in `app/identity/domain/`; dep injector check | P1 |
| API6 | Unrestricted Access to Sensitive Business Flows | ❌ absent | Mass account creation (signup), referral abuse, free-tier OpenAI drain | Cloudflare Turnstile on signup + OTP; per-IP signup cap (5/day) | **P0** |
| API7 | SSRF | ⚠️ partial | Vision URL upload, recipe import-by-URL (future) | Block RFC1918/169.254/metadata; allowlist domains; `httpx` with explicit `trust_env=False` + custom transport | P1 |
| API8 | Security Misconfiguration | ⚠️ partial | CORS wildcard risk, Traefik headers, env leak | Lock CORS to `nova-nutrition.app` + mobile schemes; add `Strict-Transport-Security`, `X-Content-Type-Options`, `Referrer-Policy`, `Permissions-Policy`, CSP `default-src 'none'` for API | **P0** |
| API9 | Improper Inventory Management | ⚠️ partial | `/docs` and `/openapi.json` exposure in prod | Gate behind `settings.ENV != "production"` or basic-auth; publish versioned OpenAPI to private repo | P1 |
| API10 | Unsafe Consumption of APIs | ✅ strong | OpenAI, Stripe, MP — all wrapped in circuit breakers | Add response schema validation (already partial); pin SDK versions; verify TLS pinning N/A (CA bundle ok) | P2 |

---

## 2. OWASP ASVS L2 — Gaps Summary

| V | Category | Status | Top gap | Action |
|---|---|---|---|---|
| V1 | Architecture | Good | Threat model not formal | Section 6 STRIDE doc |
| V2 | Authentication | Good | No MFA for high-risk actions | Defer to S2 (TOTP for account deletion + payment method change) |
| V3 | Session | Good | JWT revocation list absent | Redis denylist on logout `jti` (S1, 2h) |
| V4 | Access Control | Partial | No RBAC matrix, no ABAC for plan/billing | S1 — RBAC doc + dep |
| V5 | Validation/Encoding | Good | Pydantic strict mode not enforced | `extra='forbid'` audit (S0) |
| V6 | Stored Crypto | Weak | No field-level encryption for health conditions | S2 — pgcrypto `pgp_sym_encrypt` on `profile.conditions[]` |
| V7 | Error Handling | Good | Stack traces masked via local ErrorTracker scrubber; check generic error in `app/core/errors.py` | Verify (S0, 1h) |
| V8 | Data Protection | Partial | No data classification, no retention policy code | S1 — classification matrix + cron purge job |
| V9 | Communications | Good | HSTS not preloaded | Submit hstspreload.org (S0, 30m) |
| V10 | Malicious Code | N/A | — | GitHub native secret scanning + native Dependabot security advisories |
| V11 | Business Logic | Partial | Idempotency ✅, but no abuse detection on goals/weight (10kg/day spike) | S2 — anomaly guard in `tracking` |
| V12 | Files/Resources | Partial | EXIF strip ✅; missing MIME sniff verification | `python-magic` check (S1, 2h) |
| V13 | API/Web Services | Good | OpenAPI in prod | API9 fix |
| V14 | Config | Partial | Secrets in Dokploy env, manual rotation | Dokploy env vars + manual rotation policy (90-day rotation calendar DEFERRED until team ≥2) |

---

## 3. ISO 27001 Annex A — Pragmatic Subset

**Decision:** No formal certification (cost: ~USD 15-25k + 6mo solo-dev). Implement **spirit of controls** to enable future audit and reduce real risk.

| Annex | Control | NOVA action | Effort | Skip? |
|---|---|---|---|---|
| A.5.1 | Information security policy | 1-page `SECURITY.md` + this doc | 2h | No |
| A.5.7 | Threat intelligence | Subscribe CVE feeds (GitHub native security advisories) | 1h | No |
| A.5.23 | Cloud services security | Hostinger DPA + CF DPA on file | 1h | No |
| A.5.30 | ICT readiness for BC | DR runbook (RTO 4h / RPO 1h) | 4h | No |
| A.8.10 | Information deletion | Erasure ADR-0005 ✅ | — | Done |
| A.8.11 | Data masking | Local ErrorTracker scrubber ✅; add log scrubber middleware | 2h | No |
| A.8.12 | DLP | Overkill MVP | — | **Skip** |
| A.8.24 | Crypto | pgcrypto (deferred) | S2 | No |
| A.8.28 | Secure coding | SAST in CI (S1) | 3h | No |
| A.9 (legacy) | Access control | RBAC matrix doc | 3h | No |
| A.10 (legacy) | Cryptography | Key mgmt policy (1pg) | 2h | No |
| A.12.4 | Logging/monitoring | structlog stdout + local ErrorTracker (Loki DEFERRED until >1M log lines/day) | — | No |
| A.12.6 | Vulnerability mgmt | GitHub native Dependabot security advisories 24h SLA (no yml config) | — | Done |
| A.14.2 | Secure dev lifecycle | This plan + ADRs cover it | — | Done |
| A.16 | Incident management | Runbook + on-call rota (solo-dev: phone alerts) | 4h | No |
| A.18.1 | Legal compliance | ROPA + privacy policy | 8h | No |
| A.18.2 | Independent review | Pen-test post-launch month 3 | USD 1.5k | No |

**Skip list (overkill MVP):** A.6.3 awareness training (solo), A.7 physical security (Hostinger handles), A.8.12 DLP, A.8.25 secure SDLC formal docs, A.17 full BC plan (lean DR sufficient).

---

## 4. ISO 27017 (cloud) + 27018 (PII in cloud)

| Concern | NOVA owns | Provider owns |
|---|---|---|
| Hypervisor isolation | — | Hostinger |
| OS patching | **Yes** (unattended-upgrades) | — |
| Network ACL | **Yes** (UFW + Dokploy) | Hostinger DDoS basic |
| Edge WAF/DDoS L7 | **Yes** (CF rules) | Cloudflare L3/L4 |
| Data residency | **Yes** (choose region) | Hostinger DC location |
| Encryption at rest | **Yes** (pgcrypto app-level) | Hostinger disk (verify) |
| PII access logs | **Yes** (audit log table S1) | — |
| Sub-processor list | **Yes** (publish: OpenAI, Stripe, MP, CF, Hostinger) | — |

**LatAm + EU residency:** Hostinger EU DC (Lithuania) covers GDPR. For LGPD strict reading, BR users' data ideally in BR — defer until >5k BR users (cost: USD 50/mo extra VPS BR). Document in privacy policy.

---

## 5. Regional Compliance Status

| Regulation | Status | Gap | Action |
|---|---|---|---|
| GDPR | 60% | DPIA-lite, ROPA, DPO designation (can self-designate as <250 employees), cookie consent for web landing | S1 — ROPA + privacy policy + self-DPO declaration |
| LGPD | 55% | Encarregado (DPO equiv), ANPD registration not required <small biz, RIPD (DPIA) | Same as GDPR + Portuguese ToS |
| CCPA | 70% | "Do Not Sell" link (N/A — no sale), but disclosure required | Privacy policy section |
| Ley 29733 (PE) | 50% | RNPDP registration with ANPD-PE (required if processing PE PII commercially) | Register before public PE launch (free) |
| Ley 25.326 (AR) | 50% | AAIP registration (required, free) | Register before AR launch |
| Cookie consent mobile | N/A app | Web landing only — needs banner | Web team scope |

---

## 6. STRIDE Threat Model — Critical Contexts

### identity
| Threat | Vector | Mitigation |
|---|---|---|
| S | Token theft (replay) | Short-lived access (15m) + refresh rotation + jti denylist |
| T | OAuth state CSRF | `state` param + PKCE on Apple/Google |
| R | No audit on password change | S1 — audit_log table |
| I | User enumeration via signup error | Generic "if email exists, sent OTP" |
| D | OTP bombing | Per-email + per-IP rate limit (Redis) |
| E | JWT alg=none | RS256 enforced via `algorithms=['RS256']` ✅ |

### billing
| Threat | Vector | Mitigation |
|---|---|---|
| S | Forged webhook | HMAC strict ✅ MP, Stripe sig verify ✅ |
| T | Replay webhook | Event dedup UNIQUE ✅ |
| R | No log of subscription state changes | Audit table S1 |
| I | Subscription ID leak via BOLA | API1 fix |
| D | Webhook flood | CF rate-limit + idempotency cache ✅ |
| E | Upgrade self to premium via PATCH | API3 fix (forbid extra) |

### vision
| Threat | Vector | Mitigation |
|---|---|---|
| S | Forged image origin | N/A (we own pipeline) |
| T | Adversarial image (prompt injection in OCR) | Coach guardrails ✅ + vision output schema validation |
| R | No image hash logged | Log SHA256 + size (S1) |
| I | EXIF GPS leak | EXIF strip ✅ |
| D | Large image upload | 5MB cap + MIME sniff (S1) |
| E | SSRF via URL upload | API7 fix |

### coach
| Threat | Vector | Mitigation |
|---|---|---|
| S | Impersonate other user in conversation | JWT-scoped conversation_id |
| T | Prompt injection to leak system prompt | Guardrails ✅ + output filter |
| R | No conversation audit | Already stored in DB |
| I | Cross-user RAG leak via pgvector | Filter `WHERE user_id = ?` on every query — **audit S0** |
| D | Token-cost drain | Cost cap ADR-0004 ✅ |
| E | Medical advice → liability | Refuse policy ✅ + ToS disclaimer |

---

## 7. Roadmap

### Sprint S0 — Pre-launch blockers (this week, ~16h)
| Item | Effort | Files | Risk if skip | Covers |
|---|---|---|---|---|
| BOLA audit + `@require_owner` dep | 4h | `app/{tracking,plan,recipes,profile}/api/*` | Cross-user data leak | API1, A.9 |
| `extra='forbid'` on all `*Update` schemas | 2h | `app/*/api/schemas.py` | Privilege escalation | API3, V5 |
| CORS lockdown + security headers middleware | 1h | `app/main.py` | XSS pivot, CSRF | API8, V14 |
| OpenAPI gated in prod | 30m | `app/main.py` | Recon | API9 |
| Cloudflare Turnstile on signup + signup rate-cap | 2h | `app/identity/api/auth.py` + CF dashboard | Mass abuse, cost drain | API6 |
| pgvector tenant filter audit | 1h | `app/coach/infrastructure/rag.py`, `app/recipes/infrastructure/search.py` | Cross-tenant leak | I (STRIDE) |
| Generic error response audit | 1h | `app/core/errors.py` | Info disclosure | V7 |
| HSTS preload + headers verify | 30m | Traefik labels | Downgrade attack | V9 |
| `SECURITY.md` + VDP email | 1h | repo root | Reporting path absent | A.5.1 |
| Encrypted backup verify (Dokploy/pg_dump → age) | 4h | `scripts/backup.sh` (exists) | Backup theft | A.5.30, A.8.24 |

### Sprint S1 — Month 1 (~30h)
| Item | Effort | Risk | Covers |
|---|---|---|---|
| SAST stack: ruff S-rules (lint) + GitHub native (Secret scan + Push Protection + Code Scanning CodeQL + Dependabot security advisories) | — (active, native-only) | Unknown CVEs ship | A.8.28, A.12.6 |
| Secrets vault: SOPS+age in repo (free) — **DEFERRED** (team ≥2 trigger) | 4h | Env leak | A.8.24, V14 |
| JWT jti denylist + key rotation (kid) | 3h | Stolen token replay | V3 |
| RBAC enum + matrix doc | 3h | Future admin abuse | API5, V4 |
| Audit log table (`auth_events`, `billing_events`, `profile_changes`) | 4h | No forensics | A.12.4, R (STRIDE) |
| Loki + Promtail self-hosted (same VPS, ~200MB RAM) — **DEFERRED** (>1M log lines/day trigger) | 6h | Blind in incident | A.12.4 |
| ROPA + DPIA-lite + privacy policy v2 + ToS | 6h | Regulatory fine | A.18, GDPR/LGPD |
| MIME sniff + file size hard cap | 2h | RCE via upload | V12 |
| SSRF guards on URL ingestion | 2h | Metadata exfil | API7 |
| Anomaly guard tracking (weight delta cap) | 2h | Data poisoning | V11 |

### Sprint S2 — Month 2-3 (~40h)
| Item | Effort | Notes |
|---|---|---|
| pgcrypto field-level on `profile.conditions`, `profile.allergens` | 6h | Symmetric key in vault; query via SQL view |
| MFA TOTP for destructive actions (account delete, payment change) | 6h | `pyotp` |
| Internal pen-test checklist run (ZAP baseline + auth scan) | 4h | Free OWASP ZAP |
| External pen-test (Cobalt / HackerOne low-tier) | USD 1.5k | Post-launch month 3 |
| DR drill: full restore from backup to staging | 4h | Validates RTO/RPO |
| Data retention cron (purge soft-deleted >30d, logs >90d) | 4h | A.8.10 |
| Privacy policy translations (ES, PT-BR, EN) | 6h | LatAm + EU |
| Sub-processor public page | 2h | A.5.23 |
| Access review quarterly checklist (solo: self + Dokploy + CF + Stripe MP dashboards) | 2h | A.9 |
| Submit hstspreload | 30m | V9 |

### Sprint S3 — Month 4-6 (compliance maturity, ~30h)
| Item | Effort | Notes |
|---|---|---|
| Incident response tabletop exercise | 4h | Simulate breach |
| RNPDP-PE + AAIP-AR registrations | 4h | Free, paperwork |
| ISO 27001 readiness gap assessment (self) | 8h | Optional consultant USD 2k |
| WAF custom rules (CF) tuned from real traffic | 6h | Bot patterns |
| SBOM generation in CI (syft) | 2h | Supply chain |
| Quarterly key rotation playbook | 2h | A.10 |
| Customer-facing security page (`/security`) | 4h | Trust signal |

---

## 8. Operational Costs (new)

| Service | Free option | Paid alt | Picked |
|---|---|---|---|
| Secrets vault | SOPS+age in git | Infisical Cloud USD 0-18/mo, HashiCorp Vault | **Dokploy env vars** (current) — SOPS+age DEFERRED (team ≥2) |
| SIEM/logs | Loki+Promtail self-hosted | Better Stack USD 24/mo, Datadog USD 100+ | **structlog stdout + local ErrorTracker (ring buffer + JSONL)** — Loki DEFERRED (>1M log lines/day) |
| WAF | Cloudflare free tier | CF Pro USD 25/mo | **CF free** S0-S2, upgrade if attacked |
| SAST | ruff S-rules + CodeQL (GH native) | — | **OSS** (bandit+semgrep dropped — overlap with ruff S) |
| Dep scan | GitHub native Dependabot security advisories (no yml config) | — | **GitHub native advisories only** (pip-audit + custom dependabot.yml dropped — duplicate) |
| Secret scan | GitHub native Secret scanning + Push Protection | GitGuardian USD 0 indie | **GitHub native** (gitleaks dropped — duplicate) |
| Container scan | manual Dockerfile review one-shot | trivy / Snyk Container | **Manual review** (trivy dropped — 1 Dockerfile, low ROI pre-launch) |
| Uptime/alerting | UptimeRobot free | Better Stack | **UptimeRobot** |
| Backup offsite | Hostinger weekly snapshot (incluido plan) | B2/Hetzner Storage Box | **Hostinger weekly MVP** — upgrade off-site cuando >100 paid users |
| Pen-test | — | Cobalt USD 1.5-5k | Defer to month 3 |

**Total new monthly cost:** USD 0/mo (Hostinger weekly incluido en plan, off-site backup diferido). VPS RAM impact: ~5MB (structlog + local ErrorTracker only — Loki/Promtail deferred). Sits inside 8GB budget.

**Backup strategy MVP:**
- Único respaldo: Hostinger weekly snapshot (incluido en plan)
- RPO declarado: **hasta 7 días pérdida data**
- Riesgo asumido: SPOF Hostinger (cuenta suspendida = sin acceso backup)
- Mitigación opcional gratis: backup manual semanal `ssh vps "pg_dump nova | gzip" > ~/Backups/`
- Trigger upgrade off-site (B2 ~$1/mo o Hetzner Box €3/mo): >100 paid users OR Postgres >5GB OR primer fraude detectado

---

## 9. CI/CD Tooling

**Current stack (native-only, no custom security workflow):**

```
SAST     → ruff S-rules (in lint workflow, S101..S701 flake8-bandit)
         → GitHub Code Scanning default setup (CodeQL, free private repos)
Deps     → GitHub native Dependabot security advisories (24h SLA, no yml config)
Secrets  → GitHub native Secret scanning + Push Protection (free private repos)
Container→ Manual Dockerfile review one-shot pre-deploy (no trivy job)
DAST     → schemathesis (contract tests). zap-baseline deferred to staging phase.
```

**Rationale for removing custom `.github/workflows/security.yml` and `.github/dependabot.yml`:** every job (gitleaks, trivy fs, trivy config) had a native GitHub equivalent free for private repos as of 2024. Maintaining custom workflows was pure overhead — extra CI minutes, extra config drift surface, zero unique value. CodeQL via default setup runs automatically without yml. Push Protection blocks secrets pre-push (gitleaks only catches post-push). GitHub native dependency security advisories cover CVEs better than pip-audit/trivy fs, with zero yml maintenance.

**Owner toggles required in GitHub repo Settings → Code security:**
- Secret scanning: ON
- Push Protection: ON
- Code Scanning (CodeQL default setup): ON
- Dependency security advisories (GitHub native): ON
- Dependency security updates (GitHub native): ON
- Dependency review: ON

---

## 10. Documentation to Create

| Doc | Path | Sprint | Status |
|---|---|---|---|
| Security policy | `/SECURITY.md` | S0 | TODO |
| Vulnerability disclosure | `/SECURITY.md#disclosure` | S0 | TODO |
| Privacy policy v2 | `docs/legal/privacy-policy.md` (+ ES/PT-BR/EN) | S1 | TODO |
| ToS | `docs/legal/terms.md` | S1 | TODO |
| Data classification matrix | `docs/security/data-classification.md` | S1 | TODO |
| ROPA (Record of Processing) | `docs/security/ropa.md` | S1 | TODO |
| DPIA-lite | `docs/security/dpia.md` | S1 | TODO |
| Incident response runbook | `docs/ops/incident-response.md` | S1 | TODO |
| Backup + DR runbook | `docs/ops/backup-recovery.md` ✅ exists | — | Extend with encryption verify |
| Access control matrix | `docs/security/rbac-matrix.md` | S1 | TODO |
| Threat model | `docs/security/threat-model.md` | S2 | TODO (extend §6) |
| Sub-processor list | `docs/legal/sub-processors.md` | S2 | TODO |
| Key management policy | `docs/security/key-management.md` | S2 | TODO |

---

## Trade-offs & Honest Calls

- **No ISO 27001 cert.** Solo dev, pre-launch. Spirit-of-controls + audit-ready posture is the right level. Revisit at Series A or B2B enterprise deal.
- **No HashiCorp Vault.** Dokploy env vars + manual 90-day rotation policy (rotation calendar deferred until team ≥2). SOPS+age deferred too — migrate when team ≥3.
- **No dedicated SIEM.** Local ErrorTracker (ring buffer + JSONL) + journalctl sufficient for closed-beta. Loki/Promtail migration deferred until >1M log lines/day.
- **No formal DPO.** Self-designate under GDPR Art.37 (allowed for SMEs without "large-scale" processing — health data is borderline; if EU users >10k, hire fractional DPO ~EUR 200/mo).
- **Single VPS = single point of failure.** Accepted MVP risk. DR via Hostinger weekly snapshot (RPO 7d). Off-site backup (B2/Hetzner) diferido hasta >100 paid users. Multi-AZ at >USD 5k MRR.
- **Pen-test deferred to month 3.** Pre-launch budget tight. Run OWASP ZAP baseline self-scan as compensating control.
- **Field-level encryption deferred to S2.** App-level pgcrypto adds query complexity. Acceptable risk while VPS disk encryption is provider-managed and no breach observed.
- **Cookie banner.** Backend out of scope. Web landing team handles.
- **HIPAA.** Explicitly out of scope. Marketing must not claim "medical" or "nutrition" or scope creeps.

---

## Acceptance — Pre-launch GO/NO-GO

GO requires **all S0 items shipped + verified**. NO-GO triggers:
1. Any P0 unmitigated (BOLA, BOPLA, mass abuse, headers).
2. Backup not verified end-to-end (restore drill).
3. `SECURITY.md` + VDP missing (regulators expect a reporting path).
4. OpenAPI exposed in prod without auth.
