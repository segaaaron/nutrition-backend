# RBAC Matrix

**Standard:** OWASP API5 (Broken Function Level Authorization), ASVS V4 (Access Control)
**Code:** `app/identity/domain/roles.py` + `app/identity/presentation/dependencies.py::require_role`

---

## Role hierarchy (strict total order)

```
user (0) < premium (10) < support (20) < admin (100)
```

Each role inherits all lower-role permissions. `require_role(min_role)` checks
JWT claim role is **>=** min_role.

| Role | Numeric | Granted to | Notes |
|------|---------|-----------|-------|
| `user` | 0 | All signed-up users by default | Cannot access premium features |
| `premium` | 10 | Paying subscribers | Set by billing webhook on subscription_created |
| `support` | 20 | Internal support staff | Read access to user data for ticket resolution |
| `admin` | 100 | Owner + future ops | Full system access |

---

## Endpoint-role matrix

| Endpoint pattern | Required role | Notes |
|------------------|---------------|-------|
| `POST /identity/signup` | (none — public) | Bot defence via Turnstile (S0-deferred) |
| `POST /identity/login` | (none — public) | Rate limit + denylist |
| `POST /identity/oauth/*` | (none — public) | — |
| `GET /profile/me` | `user` | Owns own data only (BOLA enforced) |
| `PATCH /profile/me` | `user` | Pydantic extra=forbid prevents role escalation |
| `GET /plan/active` | `user` | — |
| `POST /plan/generate` | `user` | Cost cap applies |
| `POST /coach/chat` | `user` | Cost cap + guardrails |
| `POST /logs/food/*` | `user` | Idempotency required |
| `GET /recipes/*` | `user` | Public catalog |
| `POST /vision/*` | `user` | Cost cap + Turnstile (future) |
| `GET /billing/subscription` | `user` | — |
| `POST /billing/checkout` | `user` | Returns checkout URL |
| `POST /billing/cancel` | `user` | — |
| `POST /coach/swap-meal` | `premium` | (future — when feature gated) |
| `GET /coach/advanced-analytics` | `premium` | (future) |
| `GET /vision/unlimited` | `premium` | (future — higher daily quota) |
| `GET /admin/users` | `support` | (future) |
| `GET /admin/users/{id}` | `support` | (future) |
| `POST /admin/users/{id}/unlock` | `support` | (future) |
| `GET /admin/system/*` | `admin` | (future) |
| `POST /admin/feature-flags/*` | `admin` | (future) |
| `POST /admin/cost-cap/kill-switch` | `admin` | (future) |

**Status:** today only `user` and `admin` roles are issued. `premium` / `support`
are reserved for future activation. RBAC matrix above documents intent.

---

## Implementation

### Domain layer

`app/identity/domain/roles.py`:
- `Role` IntEnum: USER=0, PREMIUM=10, SUPPORT=20, ADMIN=100
- `Role.from_str(str)` / `Role.to_str() -> str` round-trip
- `role_at_least(claim_role: str, required: Role) -> bool`

### Presentation layer

`app/identity/presentation/dependencies.py`:

```python
from app.identity.domain.roles import Role

@router.get("/admin/users", dependencies=[Depends(require_role(Role.SUPPORT))])
async def list_users(...):
    ...
```

Existing `require_admin` is kept for backward compat (equivalent to
`require_role(Role.ADMIN)`).

### JWT integration

JWT access tokens carry `"role": "user"|"premium"|"support"|"admin"` claim
(set at issue time from `User.role` column). `verify_access` returns claims;
`role_at_least` does the comparison.

Role string in JWT (not numeric) keeps tokens portable across enum changes.

---

## Migration path when activating premium / support

1. Add billing webhook handler to set `user.role = "premium"` on
   `subscription_created` event, revert to `"user"` on cancellation.
2. Add support-tier endpoints with `require_role(Role.SUPPORT)`.
3. Define audit log table for any support-tier read (data access transparency).
4. Update `docs/security/RBAC.md` matrix.

---

## Anti-patterns to avoid

- ❌ Hardcoded email check: `if user.email == "owner@..."` — use Role.ADMIN
- ❌ Role string compare in business logic: use `role_at_least()`
- ❌ Adding new roles between existing tiers (renumbering breaks tokens) — append at higher number
- ❌ Deleting a role string — deprecate, never delete
- ❌ Storing role number in DB (use string for human readability + portability)
- ❌ Allowing PATCH /profile to modify `role` field (Pydantic extra=forbid blocks)
- ❌ Trusting role from request body (only JWT claim is authoritative)
