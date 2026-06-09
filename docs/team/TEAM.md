# NOVA Backend — Team Map

**Última actualización:** 2026-06-01
**Owner humano:** Miguel Ángel Saravia (mikisaraviaios@gmail.com)
**Total skills:** 9 especialistas

---

## 🔒 REGLA DE ORO

**Solo las 9 skills de este documento pueden tocar el proyecto NOVA Nutrition.**

Cualquier otra skill, plugin o asistente externo está prohibido modificar código, documentación, configuración o cualquier artefacto del repositorio. Si una tarea no calza con ninguna skill del team, se delega a Claude base sin invocar skill externa.

Excepciones permitidas:
- Subagents implementer genéricos (general-purpose) bajo orden directa del owner humano
- Subagents Explore para read-only research
- Skills oficiales superpowers (TDD, debugging, planning) como soporte metodológico

Prohibido:
- Crear nuevas skills sin aprobación explícita del owner
- Usar skills de plugins externos para tareas técnicas del backend
- Delegar trabajo NOVA-específico a skills no listadas aquí

---

## Humano

| Quién | Email | Rol |
|-------|-------|-----|
| Miguel Ángel Saravia | mikisaraviaios@gmail.com | Único dev. End-to-end. Decisión final. |

---

## Equipo skills (9)

| # | Skill | Rol principal |
|---|-------|---------------|
| 1 | `nova-backend-architect` | Arquitectura backend + Clean Arch/DDD + polyglot persistence + nutrition domain |
| 2 | `nova-qa-elite` | QA holístico + algorithm correctness audit |
| 3 | `nova-clinical-nutrition-generator` | Generador batch recetas validadas |
| 4 | `nova-api-expert` | REST/HTTP/OpenAPI/SSE contract design |
| 5 | `nova-python-expert` | Py3.12 idioms + async correctness + Decimal precision |
| 6 | `nova-design-patterns-expert` | Clean Arch + GoF + DDD + SOLID enforcement |
| 7 | `nova-best-practices-advisor` | Refactor pragmático + commit hygiene + dev quality |
| 8 | `nova-elite-test-engineer` | Property-based + mutation + contract testing |
| 9 | `nova-nutrition-algorithms-expert` | **Math engine + Plan generator basado en data cliente** |

---

## Matriz "cuándo invocar quién"

### Por tipo de tarea

| Tarea | Agente principal | Agente apoyo |
|-------|-----------------|--------------|
| Nuevo bounded context | nova-backend-architect | nova-design-patterns-expert |
| Nuevo endpoint REST | nova-api-expert | nova-elite-test-engineer |
| Cálculo BMR/TDEE/macros | nova-nutrition-algorithms-expert | nova-qa-elite |
| Generar plan personalizado | nova-nutrition-algorithms-expert | nova-clinical-nutrition-generator |
| Bug async/blocking | nova-python-expert | — |
| Refactor god class | nova-design-patterns-expert | nova-best-practices-advisor |
| Test no detecta bug | nova-elite-test-engineer | nova-qa-elite |
| Webhook gateway billing | nova-api-expert | nova-qa-elite |
| Migration Alembic | nova-qa-elite | nova-best-practices-advisor |
| PR merge ready? | nova-best-practices-advisor | nova-qa-elite |
| Algoritmo plan ranking | nova-nutrition-algorithms-expert | nova-design-patterns-expert |
| Vision AI evaluation | nova-qa-elite | nova-elite-test-engineer |
| Coach guardrails | nova-qa-elite | nova-api-expert |
| Recalibración metabólica | nova-nutrition-algorithms-expert | nova-qa-elite |
| Refactor pragmatic | nova-best-practices-advisor | — |
| Seguridad / OWASP audit | nova-qa-elite | nova-api-expert |
| Performance hot path | nova-python-expert | nova-design-patterns-expert |

### Por bounded context

| Context | Owner agente | Soporte |
|---------|-------------|---------|
| **identity** (auth, JWT, OAuth, OTP) | nova-api-expert | nova-python-expert |
| **profile** (UserProfile, allergens, conditions) | nova-backend-architect | nova-nutrition-algorithms-expert |
| **nutrition** (Mifflin, TDEE, recalibración) | **nova-nutrition-algorithms-expert** | nova-qa-elite |
| **recipes** (catálogo, hybrid search, pgvector) | nova-backend-architect | nova-clinical-nutrition-generator |
| **plan** (4-layer pipeline L1→L4) | **nova-nutrition-algorithms-expert** | nova-design-patterns-expert |
| **vision** (OpenAI gpt-4o photo→food) | nova-qa-elite | nova-api-expert |
| **voice** (Whisper STT) | nova-api-expert | nova-python-expert |
| **coach** (4-camino router, SSE) | nova-api-expert | nova-qa-elite |
| **tracking** (food_log, weight, Timescale) | nova-backend-architect | nova-elite-test-engineer |
| **grocery** (lista compra) | nova-design-patterns-expert | nova-best-practices-advisor |
| **gamification** (streaks, achievements) | nova-best-practices-advisor | — |
| **billing** (Stripe, MercadoPago) | nova-api-expert | nova-qa-elite |
| **notifications** (Push FCM/VAPID) | nova-api-expert | — |
| **core/shared** (infra, errors, redis, cost cap) | nova-python-expert | nova-design-patterns-expert |

---

## Workflow típico — nuevo feature

```
1. Brainstorm requisitos
   └── nova-best-practices-advisor (YAGNI check)

2. Diseño arquitectura
   └── nova-backend-architect
       └── nova-design-patterns-expert (patrón fit)

3. Diseño contrato API
   └── nova-api-expert (RFC compliance)

4. Diseño algoritmo (si aplica)
   └── nova-nutrition-algorithms-expert (math + scope)

5. Implementación
   └── Subagent implementer + nova-python-expert (review async/types)

6. Tests
   └── nova-elite-test-engineer (property + mutation)
       └── nova-qa-elite (nutritional correctness)

7. Pre-merge
   └── nova-best-practices-advisor (commit hygiene, PR checklist)

8. Post-deploy validación
   └── nova-qa-elite (golden set regression)
```

---

## Especialización nutricional vs técnica

```
                 NUTRICIONAL                            TÉCNICA
                    ↑                                  ↑
                    │                                  │
  nova-nutrition-    │                                  │  nova-python-
  nutrition-        │                                  │  expert
  generator         │                                  │
                    │                                  │
                    │  nova-nutrition-                 │  nova-api-expert
                    │  algorithms-expert ★             │
                    │  (puente nutricional-técnico)        │  nova-design-
                    │                                  │  patterns-expert
  nova-qa-elite ────┼──────────────────────────────────┤
  (audita ambos)    │                                  │  nova-elite-
                    │                                  │  test-engineer
                    │  nova-nutrition-backend-         │
                    │  architect                       │  nova-best-
                    │                                  │  practices-advisor
                    │  nova-backend-architect          │
                    │                                  │
                    ↓                                  ↓
```

★ `nova-nutrition-algorithms-expert` = pieza más estratégica. Une mundo nutricional (math metabolismo) con mundo técnico (output JSON plan ejecutable). Moat competitivo vs Fitia/MyFitnessPal.

---

## Boundaries de cada agente (no se cruzan)

| Agente | NO debe hacer |
|--------|---------------|
| nova-backend-architect | Implementación detallada Python; cálculos nutricionales específicos |
| nova-backend-architect | Math research-grade; recetas concretas |
| nova-qa-elite | Implementar features; diseñar arquitectura |
| nova-clinical-nutrition-generator | Arquitectura; algoritmos optimización |
| nova-api-expert | Algoritmos nutricionales; ML/optimización |
| nova-python-expert | Decisiones de arquitectura; algoritmos dominio |
| nova-design-patterns-expert | Cálculos numéricos; recetas |
| nova-best-practices-advisor | Algoritmos nutricionales; arquitectura nueva |
| nova-elite-test-engineer | Implementación features; arquitectura |
| nova-nutrition-algorithms-expert | Arquitectura backend; DB schema; recetas authoring; topics fuera de nutrición |

Si surge tarea que no calza con ningún agente → escalado al humano owner.

---

## Próxima escalada team (humanos, cuando crezca)

| Trigger | Contratar |
|---------|-----------|
| >500 DAU | 1 Senior Backend Python |
| >2k DAU + $5k MRR | + QA / Security part-time |
| iOS launch | iOS dev (Swift) |
| >$10k MRR | + DevOps / SRE |
| ISO 27001 ambition | + Compliance officer |
| Multi-region scale | + Data engineer (TimescaleDB) |

Por ahora los 10 agentes suplen a 5-6 humanos especialistas. Bus factor sigue siendo 1 (humano único), pero conocimiento documentado en `.claude/agents/` sobrevive cambios de personal futuros.

---

## Mantenimiento de este documento

- **Actualizar** cuando se agregue/modifique/quite agente
- **Versionar** vía git commits convencionales (`docs(team): ...`)
- **No editar** sin acuerdo del owner humano

Cualquier cambio de agente requiere actualizar:
1. `.claude/agents/<agent>.md` — definición del agente
2. `docs/team/TEAM.md` — este documento (matrices, boundaries)
3. `CLAUDE.md` — regla de oro si afecta política team-only
