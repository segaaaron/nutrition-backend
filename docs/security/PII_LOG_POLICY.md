# PII Log Policy (D8)

## Scope

Applies to every log statement emitted by code under `app/` at INFO, WARN,
ERROR, or CRITICAL level. DEBUG is exempt — verbose by design, disabled in
PROD log shipping.

## Banned tokens at INFO+

The following substrings are forbidden inside any INFO+ log statement
(case-insensitive, substring match):

| Token         | Why banned                                                     |
| ------------- | -------------------------------------------------------------- |
| `bmi`         | Biometric → indirectly identifying when combined with country  |
| `peso`        | Spanish "weight" — same risk                                   |
| `weight_kg`   | Biometric                                                      |
| `condicion`   | Medical condition name — sensitive health data (GDPR Art. 9)   |
| `alergia`     | Allergy — health data                                          |
| `allergen`    | Allergy — health data                                          |
| `email`       | Direct identifier                                              |
| `phone`       | Direct identifier                                              |

## Enforcement

`make pii-audit` (also runs as part of `make check`) walks `app/` and
fails when any INFO+ logger call contains a banned token. Continuation
lines of multi-line log calls are scanned together.

CI must run `make check` so PRs are blocked on violations.

## What to do instead

1. **Downgrade to DEBUG.** If the field is genuinely useful only for local
   debugging, use `logger.debug(...)`.
2. **Hash the identifier.** When persistent correlation is needed (e.g.
   "this user repeatedly failed X"), log a stable hash of `user_id`
   (already a UUID, so it's an opaque token by itself — never log
   `email`, `phone`, or raw biometrics).
3. **Replace with bucket / class.** Instead of `bmi=29.4`, log
   `bucket=overweight`. Instead of `weight_kg=82.3`, log `kg_band=80-90`.
4. **Aggregate.** Telemetry that drives dashboards should hit Prometheus
   counters / histograms, not the log stream.

## Example fixes

```python
# BAD — leaks BMI + raw kcal into PROD logs
_logger.info("intake_bias bucket=%s bmi=%s raw=%s", bucket, bmi, raw_kcal)

# GOOD — bucket alone, DEBUG tier
_logger.debug("intake_bias bucket=%s multiplier=%s", bucket, multiplier)
```

## Adding a new token to the ban list

Edit `BANNED_TOKENS` in `scripts/pii_log_grep.py` and update the table
above. Run `make pii-audit` to confirm the ban list catches the new
pattern.
