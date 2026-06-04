# NOVA k6 Load Tests

k6 scripts for performance baselines, sustained load, and burst-spike validation.

Scripts are **authored only** in this session — execution against staging is deferred until
the staging environment exists (see `docs/PROJECT_STATE.md` item #32).

---

## Scripts

| Script | Profile | Thresholds |
|---|---|---|
| `k6_baseline_smoke.js` | 5 RPS, 30s sustain | p95 < 500ms, err < 1% |
| `k6_steady_100rps_10m.js` | 100 RPS, 10 min mix | p95 < 800ms, err < 2% |
| `k6_spike_500rps_30s.js` | 0→500 RPS spike, 30s sustain | p95 < 1500ms, err < 5%, 5xx < 100 |
| `k6_baseline.js` *(legacy)* | Original multi-scenario harness | retained for reference |

### Endpoint mix (steady + spike)

| Weight | Endpoint | Notes |
|---|---|---|
| 40% | `GET /v1/recipes/search?q=…` | Redis cache hit path |
| 20% | `GET /v1/plan/me` | Redis 24h cache |
| 15% | `POST /v1/tracking/water` | Redis INCR write |
| 10% | `POST /v1/tracking/weight` | Postgres insert |
| 10% | `GET /v1/identity/me` | JWT verify only |
| 5%  | `POST /v1/coach/chat` (SSE) | LLM-backed, expensive |

`Idempotency-Key` UUIDv4 header injected automatically on write endpoints (D12 contract).

---

## Run locally

```bash
# 1. Stack up
docker compose -f docker-compose.mvp.yml up -d

# 2. Mint a test JWT (use scripts/seed_load_users.py once it exists, or paste a known-good token)
export TOKEN="ey..."

# 3. Smoke
make load-smoke           BASE_URL=http://localhost:8000 TOKEN=$TOKEN
make load-steady          BASE_URL=http://localhost:8000 TOKEN=$TOKEN
make load-spike           BASE_URL=http://localhost:8000 TOKEN=$TOKEN
```

Or directly:

```bash
k6 run -e BASE_URL=http://localhost:8000 -e TOKEN=$TOKEN \
  tests/load/k6_baseline_smoke.js
```

## Run against staging (when it exists)

```bash
export BASE_URL=https://staging.api.nova-nutrition.com
export TOKEN=$(scripts/mint_load_test_jwt.py --user load-test-001)
k6 run -e BASE_URL=$BASE_URL -e TOKEN=$TOKEN \
  --summary-export=tests/load/results/staging_$(date +%Y%m%d_%H%M%S).json \
  tests/load/k6_steady_100rps_10m.js
```

---

## CI regression gate (deferred — pseudocode)

When staging env is live, the following GitHub Actions workflow gates merges on >15%
p95 regression vs the stored baseline JSON in `tests/load/results/baseline.json`.

```yaml
# .github/workflows/perf-regression.yml  (NOT YET COMMITTED — pseudocode)
name: perf-regression
on:
  pull_request:
    paths: ['app/**', 'tests/load/**']
jobs:
  k6:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: grafana/setup-k6-action@v1
      - name: Run smoke against ephemeral staging
        env:
          BASE_URL: ${{ secrets.STAGING_URL }}
          TOKEN: ${{ secrets.STAGING_LOAD_TOKEN }}
        run: |
          k6 run --summary-export=current.json tests/load/k6_baseline_smoke.js
      - name: Compare vs baseline
        run: |
          python scripts/compare_k6_p95.py \
            --baseline tests/load/results/baseline.json \
            --current current.json \
            --threshold 0.15
```

The compare script (not yet written) must:
- Load both JSON summary exports.
- Compute p95 delta per endpoint tag.
- Fail with exit 1 if any endpoint's p95 regressed > 15%.
- Print a markdown table for PR comment.

---

## Interpreting results

| Signal | Meaning | Action |
|---|---|---|
| `http_req_duration p(95)` over threshold | Latency budget breached | Profile slowest endpoint; check Redis cache hit rate |
| `errors rate` high | Functional failure | Check logs; rule out test-data issue first |
| `server_5xx count > 0` during spike | Real backend crash | P0 — investigate; do not ship |
| `rate_limited_429 count` increasing | Rate limiter healthy | Expected; verify `Retry-After` header present |
| Latency increases monotonically | Likely memory leak or connection pool exhaustion | Profile with `py-spy` against soak run |
| `vus_max` reached often | Need more `preAllocatedVUs` | Tune scenario; not a backend issue |

### Recovery test

After running the spike, immediately re-run `k6_baseline_smoke.js`. p95 must return to
baseline within 30s of spike end. If not, investigate stuck connections or runaway tasks.

---

## File contracts (do not break without owner sign-off)

- Scripts must read `BASE_URL` and `TOKEN` from env, never hardcoded.
- All write endpoints must inject a fresh `Idempotency-Key` (UUIDv4).
- 429 with `Retry-After` is a SUCCESS (rate limiter doing its job under spike).
- 5xx is always a FAILURE.
