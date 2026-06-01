# Security Backlog — Deferred Until Traction

**Status:** Active backlog
**Trigger to revisit:** ≥100 active paying users
**Created:** 2026-06-01
**Owner:** Miguel Ángel Saravia

---

## 🚦 Activation rule

**Do NOT pull items from this backlog until at least one of these triggers fires:**

- ✅ 100+ active paying users
- ✅ First abuse incident detected (signup spam, API abuse, etc.)
- ✅ First security incident reported via VDP
- ✅ B2B/enterprise customer contract demands audit-readiness
- ✅ Direct owner instruction to start S0-residual sprint

Until then: items remain frozen. No partial pickup.

---

## 🟡 Sprint S0 — RESIDUAL (deferred from pre-launch)

Items planned for Sprint S0 but de-prioritised because zero users = zero exploit surface.

| # | Item | Esfuerzo | OWASP/ISO | Riesgo si NO se hace |
|---|------|----------|-----------|----------------------|
| S0-F | **Anti-sniff / Proxyman defense** | 3h | API8, ASVS V9 | Atacante con root CA en device ve tráfico HTTPS |
| S0-G | **Cloudflare Turnstile signup** | 2h | API6 | Bot crea 10k cuentas, drena OpenAI cost cap |
| S0-H | **pgvector tenant filter audit** | 2h | API1 | Recipe search leak embeddings entre usuarios |
| S0-I | **SSRF guard vision URL upload** | 2h | API7 | Atacante apunta a `169.254.169.254` (cloud metadata) o RFC1918 |
| S0-J | **JWT key rotation (kid header)** | 3h | ASVS V2 | Compromised key sin rotation = downtime para invalidar |
| S0-K | **Per-IP global rate-limit Traefik** | 1h | API4 | Volumetric attack pasa rate-limit por-user |

**Total esfuerzo S0 residual:** ~13h
**Costo:** $0
**Bloqueante real hoy:** NO (zero users)

---

## Razón de diferimiento

| Argumento | Detalle |
|-----------|---------|
| **Surface ataque = 0** | Sin usuarios no hay PII para exfiltrar, sin pagos no hay fraude, sin embeddings no hay leak |
| **Mejor invertir en producto** | Tiempo limitado de solo-dev → priorizar features que atraen primeros 100 usuarios |
| **YAGNI temporal** | Implementar defenses sin uso real = sobre-ingeniería pre-revenue |
| **Capa existente suficiente MVP** | Cloudflare default DDoS + Traefik HTTPS + S0 ya implementado cubren amenazas reales hoy |

---

## Mitigaciones compensatorias mientras tanto

Para reducir riesgo mientras backlog frozen:

1. **Cloudflare default DDoS** activo (gratis, sin config extra)
2. **Cost cap OpenAI** ya enforced ($1.50/user/día + kill switch global)
3. **Rate limit por-user Redis** ya implementado
4. **Sentry observabilidad** detecta abuse patterns
5. **JWT short TTL** (15min) + refresh token rotation
6. **Idempotency Redis+DB** previene duplicados accidentales/maliciosos
7. **MercadoPago HMAC strict** ya cierra webhook spoof

Si surge incident antes de 100 usuarios → activar item específico fuera del proceso normal.

---

## Trigger de reactivación

```
Cuando se cumpla CUALQUIERA:

[ ] 100+ paying users active monthly
[ ] First abuse / security incident
[ ] B2B customer audit demand
[ ] Owner explicit instruction

→ Notificar a humano + abrir Sprint S0-residual
→ Estimar 2 días dev focused para completar 6 items
→ Re-evaluar prioridades (algunos pueden estar obsoletos)
```

---

## Items que NO van a este backlog (verdaderos P0 ya cerrados)

Lo que SÍ se hizo pre-launch porque hubiera sido negligencia diferir:

- ✅ MercadoPago HMAC (fraude pagos directo)
- ✅ JWT migration pyjwt (CVE surface)
- ✅ Idempotency DB fallback (duplicados Redis restart)
- ✅ BOLA audit (data leak user A → user B)
- ✅ Pydantic extra=forbid (mass assignment)
- ✅ JWT revocation Redis (logout no invalidaba)
- ✅ Security headers + CORS lock + /docs gate
- ✅ Coach guardrails expandidos
- ✅ Sentry + PII scrubber

---

## Recordatorio para próximo asistente

Si lees esto y el repo ya tiene ≥100 usuarios:

1. Avisa al owner humano
2. Estima 2 días dev para Sprint S0-residual completo
3. Re-validar que los 6 items siguen relevantes (algunos pueden estar obsoletos)
4. Crear plan implementación estilo bite-sized
5. Dispatch subagents implementer

No tocar este backlog sin trigger explícito.

---

## Sprints S1, S2, S3 — referencia

Items futuros no en este backlog (S1, S2, S3) están en `docs/security/PLAN.md` con triggers propios. Este BACKLOG.md es exclusivo para S0-residual.
