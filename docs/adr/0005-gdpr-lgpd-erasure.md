# ADR-0005 — GDPR / LGPD / LFPDPPP data erasure

- Status: Accepted
- Date: 2026-05-30
- Deciders: nova-nutrition-backend-architect, nova-qa-elite
- Supersedes: n/a

## Context

NOVA stores health-class PII (weight, biometrics, conditions, food intake,
coach chat). EU GDPR (Art. 17), Brazilian LGPD (Art. 18 §VI) and Mexican
LFPDPPP all grant a right to erasure. The previous spec had no erasure path,
no portability endpoint, and a tension between the append-only `audit_log`
table and the requirement to delete user PII.

## Decision

### Endpoints
- `DELETE /me`: soft-delete request. Sets `users.deletion_requested_at = now()`,
  invalidates all refresh tokens, logs out all sessions, and schedules a hard
  delete after a 30-day grace window (LFPDPPP-aligned). During grace, the user
  can `POST /me/cancel-deletion` to abort.
- `GET /me/export`: returns a single JSON document with every row keyed to the
  user across all bounded contexts (profile, goals, plans, food/water/weight
  logs, coach messages, achievements). Streaming response, async-generated
  through a worker job for users with large log histories.

### Hard-delete (T+30d background job)
- **Hard delete** rows in: `user_profiles`, `nutritional_goals`,
  `refresh_tokens`, `otp_codes`, `plans`, `plan_days`, `plan_meals`,
  `plan_generation_seeds`, `food_logs`, `water_logs`, `weight_logs`,
  `fasting_sessions`, `daily_goals`, `grocery_lists`, `grocery_items`,
  `streaks`, `achievements`, `coach_conversations`, `coach_messages`,
  `coach_sse_tickets`, `progress_photos` (and blob storage when added).
- **Pseudonymise** in `audit_log`: set `user_id = NULL`, scrub `metadata->>'email'`,
  keep the row. Justification: audit trail integrity is the legal basis for
  retention; rows without user_id are not personal data.
- **Cascade**: FK constraints use `ON DELETE CASCADE` from `users(id)` for
  everything except `audit_log` (which uses `ON DELETE SET NULL`).
- **Finalise**: set `users.deleted_at = now()`, zero out `email`,
  `password_hash`, `oauth_subject`, retain `id` as a tombstone.

### Audit-log retention exception
- Append-only `audit_log` keeps **pseudonymised** rows for 24 months for
  security/fraud-investigation purposes. Documented in the privacy policy as a
  legitimate-interest basis under GDPR Art. 6(1)(f).

### Re-registration
- Re-registering with the same email after a hard delete creates a new `users.id`;
  no data is restored. The tombstone row prevents email re-use within the grace
  window.

## Consequences

- Compliance posture is defensible for EU / BR / MX users at MVP launch.
- One background job (`hard_delete_pending_users_task`) runs daily; idempotent.
- Coach analytics on aggregate trends survive deletion because user_id is
  pseudonymised (NULL), not deleted.

## References

- GDPR Art. 17 (Right to erasure); Art. 20 (Portability).
- LGPD Art. 18 §VI; LFPDPPP Art. 25.
- Spec §7 (users, audit_log), §8 (DELETE /me, GET /me/export).
- Tests: `tests/integration/identity/test_user_erasure.py::test_delete_me_removes_all_pii_traces`,
  `tests/integration/identity/test_user_erasure.py::test_audit_log_user_id_pseudonymised`,
  `tests/integration/identity/test_user_export.py::test_export_contains_all_owned_rows`.
