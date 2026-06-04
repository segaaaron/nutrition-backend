// k6 steady 100 RPS / 10 min — NOVA backend (item #30B).
//
// Purpose: sustained mixed-workload baseline for staging.
// Validates p95/error budget under realistic traffic mix.
//
// Usage:
//   k6 run -e BASE_URL=https://staging.api.nova-nutrition.com \
//     -e TOKEN=<bearer> tests/load/k6_steady_100rps_10m.js
//
// Mix (weighted random per iteration):
//   40% GET /v1/recipes/search        (Redis cache hit expected)
//   20% GET /v1/plan/me               (Redis 24h cache)
//   15% POST /v1/tracking/water       (Redis INCR)
//   10% POST /v1/tracking/weight      (Postgres insert)
//   10% GET /v1/identity/me           (JWT verify only)
//    5% POST /v1/coach/chat (SSE)     (expensive, LLM)
//
// Thresholds:
//   - p95 < 800ms (excluding SSE bucket)
//   - error rate < 2%

import http from 'k6/http';
import { check } from 'k6';
import { Rate, Trend } from 'k6/metrics';
import { uuidv4 } from 'https://jslib.k6.io/k6-utils/1.4.0/index.js';

const BASE = __ENV.BASE_URL || 'http://localhost:8000';
const TOKEN = __ENV.TOKEN || '';

const errorRate = new Rate('errors');
const readLatency = new Trend('read_latency');
const writeLatency = new Trend('write_latency');
const coachLatency = new Trend('coach_sse_latency');

export const options = {
  scenarios: {
    steady_100rps_10m: {
      executor: 'constant-arrival-rate',
      rate: 100,
      timeUnit: '1s',
      duration: '10m',
      preAllocatedVUs: 100,
      maxVUs: 300,
    },
  },
  thresholds: {
    'http_req_duration{kind:read}': ['p(95)<800'],
    'http_req_duration{kind:write}': ['p(95)<800'],
    errors: ['rate<0.02'],
    http_req_failed: ['rate<0.02'],
  },
};

const headers = (extra = {}) => ({
  headers: {
    Authorization: TOKEN ? `Bearer ${TOKEN}` : '',
    'Content-Type': 'application/json',
    ...extra,
  },
});

const idempotencyHeaders = () =>
  headers({ 'Idempotency-Key': uuidv4() });

const queries = ['arroz', 'pollo', 'quinoa', 'frijol', 'pescado', 'lentejas'];

function pickAction() {
  const r = Math.random();
  if (r < 0.40) return 'recipes_search';
  if (r < 0.60) return 'plan_me';
  if (r < 0.75) return 'water';
  if (r < 0.85) return 'weight';
  if (r < 0.95) return 'identity_me';
  return 'coach_chat';
}

export default function () {
  const action = pickAction();
  let res, ok;

  switch (action) {
    case 'recipes_search': {
      const q = queries[Math.floor(Math.random() * queries.length)];
      res = http.get(`${BASE}/v1/recipes/search?q=${q}`, {
        ...headers(),
        tags: { kind: 'read', endpoint: 'recipes_search' },
      });
      ok = check(res, { 'recipes_search 2xx': (r) => r.status >= 200 && r.status < 300 });
      readLatency.add(res.timings.duration);
      break;
    }
    case 'plan_me': {
      res = http.get(`${BASE}/v1/plan/me`, {
        ...headers(),
        tags: { kind: 'read', endpoint: 'plan_me' },
      });
      ok = check(res, { 'plan_me 2xx/404': (r) => r.status < 500 });
      readLatency.add(res.timings.duration);
      break;
    }
    case 'water': {
      res = http.post(
        `${BASE}/v1/tracking/water`,
        JSON.stringify({ volume_ml: 250 }),
        { ...idempotencyHeaders(), tags: { kind: 'write', endpoint: 'water' } },
      );
      ok = check(res, { 'water 2xx': (r) => r.status < 400 });
      writeLatency.add(res.timings.duration);
      break;
    }
    case 'weight': {
      res = http.post(
        `${BASE}/v1/tracking/weight`,
        JSON.stringify({ weight_kg: 70.5 }),
        { ...idempotencyHeaders(), tags: { kind: 'write', endpoint: 'weight' } },
      );
      ok = check(res, { 'weight 2xx': (r) => r.status < 400 });
      writeLatency.add(res.timings.duration);
      break;
    }
    case 'identity_me': {
      res = http.get(`${BASE}/v1/identity/me`, {
        ...headers(),
        tags: { kind: 'read', endpoint: 'identity_me' },
      });
      ok = check(res, { 'identity_me 2xx': (r) => r.status === 200 });
      readLatency.add(res.timings.duration);
      break;
    }
    case 'coach_chat': {
      // SSE: capture TTFB only (k6 http does not stream). Acceptable for baseline.
      res = http.post(
        `${BASE}/v1/coach/chat`,
        JSON.stringify({ message: 'que como hoy?', locale: 'es' }),
        { ...headers({ Accept: 'text/event-stream' }), tags: { kind: 'sse', endpoint: 'coach_chat' } },
      );
      ok = check(res, { 'coach_chat opened': (r) => r.status < 500 });
      coachLatency.add(res.timings.duration);
      break;
    }
  }
  errorRate.add(!ok);
}
