# NOVA Plan API Contract — Mobile (iOS + Android)

**Version:** 0.1 (skeleton) — 2026-06-01
**Audience:** iOS Swift / SwiftUI + Android Kotlin / Jetpack Compose
**Status:** SKELETON — endpoints to be implemented per master plan §7

This document is the planned contract for the plan-generation API. Backend implementation is P2 backlog. Mobile team can read schemas to plan UI now; consume after backend ships.

## 1. Endpoints overview

| Method | Path | Scope | Status |
|--------|------|-------|--------|
| POST | `/v1/plan/generate` | `plan:write` | 🟡 Planned |
| GET | `/v1/plan/me` | `plan:read` | 🟡 Planned |
| GET | `/v1/plan/jobs/{job_id}` | `plan:read` | 🟡 Planned (async) |
| POST | `/v1/plan/me/swap/{meal_id}` | `plan:write` | 🟡 Planned |
| POST | `/v1/plan/me/recalibrate` | `plan:write` | 🟡 Planned |
| POST | `/v1/plan/me/recalibrate/{id}/accept` | `plan:write` | 🟡 Planned |
| POST | `/v1/plan/me/recalibrate/{id}/reject` | `plan:write` | 🟡 Planned |
| GET | `/v1/plan/history` | `plan:read` | 🟡 Planned |
| GET | `/v1/plans/{plan_version_id}` | `plan:read` | 🟡 Planned (immutable) |

## 2. POST /v1/plan/generate

Request:
```http
POST /v1/plan/generate
Authorization: Bearer <jwt>
Idempotency-Key: <uuid v4>
Content-Type: application/json
Prefer: respond-async   # optional

{
  "start_date": "2026-06-02",
  "goal_override": null,
  "notes": null
}
```

Response — sync 201 (<800ms):
```http
HTTP/1.1 201 Created
Location: /v1/plans/abc-def-...

{
  "plan_version_id": "uuid",
  "algorithm_version": "0.1.0",
  "kcal_target": "2056.00",
  "macros": {
    "protein_g": "103",
    "carbs_g": "283",
    "fat_g": "57",
    "fiber_g_min": "25"
  },
  "generated_at": "2026-06-02T07:00:00Z",
  "days": [
    {
      "date": "2026-06-02",
      "meals": [
        {
          "slot_index": 0,
          "meal_time": "breakfast",
          "recipe_id": "nova_meal_b01_001",
          "recipe_snapshot": {
            "name": "Bowl de Avena Mediterránea con Higos y Almendras",
            "image_url": "https://storage.googleapis.com/nova-nutrition-public/placeholder.webp",
            "kcal": 321,
            "macros": {"protein_g": 12, "carbs_g": 48, "fat_g": 9}
          }
        }
      ]
    }
  ]
}
```

Response — async 202 (if budget exceeded):
```http
HTTP/1.1 202 Accepted

{
  "job_id": "uuid",
  "status_url": "/v1/plan/jobs/<uuid>",
  "eta_ms": 2500
}
```

## 3. Error contract (RFC 7807)

| Status | Type URN | Detail format |
|-------:|----------|---------------|
| 422 | `urn:nova:problem:plan:segment-unsupported-mvp` | only `diabetes_t1` blocked post H2 lifts |
| 422 | `urn:nova:problem:plan:no-eligible-recipes` | constraints too strict, surface message |
| 422 | `urn:nova:problem:plan:plateau-detection-pending` | retry later, ETA in detail |
| 429 | `urn:nova:problem:plan:cost-cap-exceeded` | `Retry-After: 3600` |
| 503 | `urn:nova:problem:plan:generation-failed` | retry safe, `Retry-After` |

## 4. POST /v1/plan/me/swap/{meal_id}

```http
POST /v1/plan/me/swap/<meal_id>
Authorization: Bearer <jwt>
Idempotency-Key: <uuid v4>

{}
```

Returns 200 with updated meal + new `plan_version_id`. Old plan_version remains in history (immutable).

## 5. POST /v1/plan/me/recalibrate

Manual recalibration (user request):
```http
POST /v1/plan/me/recalibrate
Authorization: Bearer <jwt>
Idempotency-Key: <uuid v4>

{ "reason": "manual" }
```

Returns 202 + diff preview URL + 24h acceptance window. User accepts → new plan_version becomes active. Auto-accepts after 24h if silent.

System-triggered (plateau): worker creates pending recalibration → push notify `{type: "plan.recalibration_pending", recalibration_id}`.

## 6. GET /v1/plan/me

Returns currently active plan. Headers:
- `ETag: <hash>`
- `Cache-Control: private, max-age=60`
- `X-Pending-Recalibration: <id>` if one is pending acceptance

## 7. GET /v1/plan/history

Cursor pagination:
```http
GET /v1/plan/history?cursor=<base64>&limit=20
```

Response:
```json
{
  "items": [
    {
      "plan_version_id": "uuid",
      "algorithm_version": "0.1.0",
      "generated_at": "2026-06-02T07:00:00Z",
      "status": "active|superseded|rejected|pending_acceptance",
      "summary": "Weight loss · LatAm · 2056 kcal/day"
    }
  ],
  "next_cursor": "<base64>"
}
```

## 8. GET /v1/plans/{plan_version_id}

Returns immutable plan snapshot. `Cache-Control: private, max-age=31536000, immutable`.

## 9. Mobile UX notes

- Pull-to-refresh on plan view triggers GET `/v1/plan/me` with ETag.
- Pending recalibration banner: "Tu plan ha sido ajustado. [Ver cambios] [Aceptar] [Rechazar]"
- Swap meal: bottom sheet with 3-5 alternatives ranked by Layer 3 + variety.
- 24h auto-accept countdown for system-triggered recalibration.
- All plan_version_id values should be logged client-side for crash reporting.

## 10. Algorithm version exposure

`algorithm_version` semver appears in every plan response. Mobile clients SHOULD include this in crash reports for backend-side reproduction.

Old algorithm_version plans return `Deprecation: true` header + `Sunset` header per RFC 8594 when version is end-of-lifed.

## 11. Status — implementation roadmap (P2)

| # | Item | Effort |
|---|------|--------|
| 1 | POST `/v1/plan/generate` endpoint + idempotency-key dedupe | 1 sem |
| 2 | Plan-versions storage + persistence | 2d |
| 3 | RFC 7807 problem-types middleware | 1d |
| 4 | GET `/v1/plan/me` with ETag | 1d |
| 5 | Swap endpoint | 2d |
| 6 | Recalibration saga (DetectPlateau → RecomputeTDEE → RegeneratePlan → NotifyUser) | 1 sem |
| 7 | History cursor pagination | 2d |
| 8 | Immutable plan_version_id endpoint | 1d |

End skeleton. Detailed spec ships when endpoints land.
