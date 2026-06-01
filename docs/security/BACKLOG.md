# Security Backlog

**Status:** Sprint S0 COMPLETE. Backlog cleared.
**Last updated:** 2026-06-01

---

## ✅ Sprint S0 — all items SHIPPED

| # | Item | Commit | Status |
|---|------|--------|--------|
| S0-A | Security headers + CORS + /docs gate | `d9d6b4e` | ✅ Done |
| S0-B | BOLA audit + assert_owns | `91d54e9` | ✅ Done |
| S0-C | Pydantic extra='forbid' (10 schemas) | `805d63d` | ✅ Done |
| S0-D | JWT revocation Redis denylist | `448d16a` | ✅ Done |
| S0-E | SECURITY.md + VDP | `bcf6dde` | ✅ Done |
| S0-F | Anti-sniff Proxyman defense | `44d2dad` | ✅ Done |
| S0-H | pgvector tenancy audit + regression guard | `64e6741` | ✅ Done |
| S0-I | SSRF guard (safe_async_client) | `b631203` | ✅ Done |
| S0-J | JWT key rotation kid header | `5ce650a` | ✅ Done |
| S0-K | Per-IP global rate-limit | `3c168ac` | ✅ Done |

**Deferred from S0:**

| Item | Reason | Re-evaluate when |
|------|--------|------------------|
| Cloudflare Turnstile signup | Owner instruction to defer — no CF setup yet | After domain + CF account configured |

---

## Sprint S1 (mes 1 post-launch) — deferred

| Item | Esfuerzo | Trigger |
|------|----------|---------|
| RBAC matrix | 4h | Admin endpoints added |
| MIME sniff verification vision | 2h | First vision upload incident |
| Data classification matrix | 2h | Compliance audit pending |
| Data retention cron | 4h | DB > 5GB OR 90d post-launch |
| HSTS preload submit | 30min | Domain stable 30d |
| SAST in CI (bandit + semgrep) | 3h | First PR review batch |
| Secret scan CI (gitleaks) | 1h | Same |
| Dep scan CI (pip-audit + dependabot) | 2h | Same |
| Container scan CI (trivy) | 2h | Same |
| Anomaly guard tracking | 3h | First abuse pattern detected |
| Privacy Policy + ToS templates | 4h | Pre-launch legal review |
| Cookie consent (mobile-first decision) | 2h | EU launch |

---

## Sprint S2 (mes 2-3 post-launch) — deferred

| Item | Esfuerzo | Costo | Trigger |
|------|----------|-------|---------|
| pgcrypto field-level encryption | 8h | $0 | First B2B customer demand |
| MFA TOTP (deletion + payment) | 6h | $0 | First fraud incident |
| Pen-test externo | 0h dev | $1.5k | $5k MRR + funding |
| OWASP ZAP baseline en CI | 4h | $0 | After SAST in place |
| SOPS + age secrets | 6h | $0 | Team ≥2 members |
| Loki + Promtail self-hosted SIEM | 4h | $0 | Sentry quota hit |
| ROPA — Record of Processing | 6h | $0 | GDPR DSAR received |
| DPIA-lite | 4h | $0 | Same |
| App attestation hooks | 6h | $0 | Mobile app published |

---

## Sprint S3 (mes 4-6 post-launch) — deferred

| Item | Esfuerzo | Costo | Trigger |
|------|----------|-------|---------|
| WAL archiving PITR | 4h | $0 | 1k DAU |
| Disaster Recovery drill quarterly | 4h | $0 | First production data |
| Backup encryption + off-site | 4h | $1-5/mo | 100+ paid users (per owner rule) |
| Access review log + cron | 3h | $0 | Team ≥3 |
| Threat model formal STRIDE | 8h | $0 | Pre-Series A |
| Incident Response runbook | 4h | $0 | First incident OR pre-launch |
| Vulnerability tracking CVD | 3h | $0 | First VDP report |
| Compliance audit prep | 4h | $0 | Pre-Series A |

---

## Compensating controls active

While S1-S3 items defer, these layer 1 controls protect:

- Cloudflare DDoS + edge filtering
- Cost cap OpenAI ($1.50/user/day + kill switch)
- Per-user Redis rate limit + per-IP rate limit (S0-K)
- JWT short TTL (15min) + refresh rotation + denylist (S0-D) + key rotation (S0-J)
- Idempotency Redis+DB fallback
- MercadoPago HMAC strict
- Sentry observability + PII scrubber
- Security headers + CORS lock + /docs gate prod (S0-A)
- BOLA assert_owns helper (S0-B)
- Pydantic extra=forbid mass-assignment block (S0-C)
- SSRF guard outbound HTTP (S0-I)
- Anti-sniff Proxyman/Charles detection (S0-F)
- Coach guardrails (medical + offtopic + prompt injection)
- pgvector tenancy regression guard (S0-H)
- VDP + SECURITY.md disclosure channel (S0-E)

---

## Reminder for next assistant

If user reports first abuse incident OR 100+ users OR B2B audit demand:
1. Notify owner: "Backlog trigger fired."
2. Review Sprint S1 items first (cheap quick wins).
3. Estimate plan + propose implementation.
4. Do NOT auto-implement. Wait for owner confirmation.
