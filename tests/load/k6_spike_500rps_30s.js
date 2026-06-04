// k6 spike 500 RPS / 30s — NOVA backend (item #30C).
//
// Purpose: burst surge to validate rate-limit kicks in at IP cap, no crashes,
// graceful degradation, and clean recovery to baseline.
//
// Usage:
//   k6 run -e BASE_URL=https://staging.api.ms-tech-stack.cloud \
//     -e TOKEN=<bearer> tests/load/k6_spike_500rps_30s.js
//
// Stages: ramp 0→500 in 10s → sustain 500 RPS 30s → ramp down 10s.
//
// Thresholds (degraded but bounded):
//   - p95 < 1500ms
//   - error rate < 5%   (429s expected once IP/user cap fires; counted as success)
//
// What we validate beyond thresholds:
//   - rate limiter returns 429 with Retry-After header
//   - no 5xx storms (circuit breakers + connection pool bounded)
//   - post-spike, baseline recovers (verify by re-running smoke after)

import http from 'k6/http';
import { check } from 'k6';
import { Rate, Trend, Counter } from 'k6/metrics';
import { uuidv4 } from 'https://jslib.k6.io/k6-utils/1.4.0/index.js';

const BASE = __ENV.BASE_URL || 'http://localhost:8000';
const TOKEN = __ENV.TOKEN || '';

const errorRate = new Rate('errors');
const rateLimited = new Counter('rate_limited_429');
const serverErrors = new Counter('server_5xx');
const latency = new Trend('latency_all');

export const options = {
  scenarios: {
    spike_500rps_30s: {
      executor: 'ramping-arrival-rate',
      startRate: 0,
      timeUnit: '1s',
      preAllocatedVUs: 300,
      maxVUs: 800,
      stages: [
        { target: 500, duration: '10s' },  // ramp burst
        { target: 500, duration: '30s' },  // sustain
        { target: 0, duration: '10s' },    // recovery
      ],
    },
  },
  thresholds: {
    http_req_duration: ['p(95)<1500'],
    errors: ['rate<0.05'],
    server_5xx: ['count<100'],  // hard cap on real server errors
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

const queries = ['arroz', 'pollo', 'quinoa', 'frijol'];

function pickAction() {
  const r = Math.random();
  if (r < 0.40) return 'recipes_search';
  if (r < 0.60) return 'plan_me';
  if (r < 0.75) return 'water';
  if (r < 0.85) return 'weight';
  if (r < 0.95) return 'identity_me';
  return 'coach_chat';
}

function classify(res) {
  if (res.status === 429) {
    rateLimited.add(1);
    return true; // 429 is acceptable success under spike
  }
  if (res.status >= 500) {
    serverErrors.add(1);
    return false;
  }
  return res.status >= 200 && res.status < 400;
}

export default function () {
  const action = pickAction();
  let res;

  switch (action) {
    case 'recipes_search': {
      const q = queries[Math.floor(Math.random() * queries.length)];
      res = http.get(`${BASE}/v1/recipes/search?q=${q}`, headers());
      break;
    }
    case 'plan_me':
      res = http.get(`${BASE}/v1/plan/me`, headers());
      break;
    case 'water':
      res = http.post(
        `${BASE}/v1/tracking/water`,
        JSON.stringify({ volume_ml: 250 }),
        idempotencyHeaders(),
      );
      break;
    case 'weight':
      res = http.post(
        `${BASE}/v1/tracking/weight`,
        JSON.stringify({ weight_kg: 70.5 }),
        idempotencyHeaders(),
      );
      break;
    case 'identity_me':
      res = http.get(`${BASE}/v1/identity/me`, headers());
      break;
    case 'coach_chat':
      res = http.post(
        `${BASE}/v1/coach/chat`,
        JSON.stringify({ message: 'hola', locale: 'es' }),
        headers({ Accept: 'text/event-stream' }),
      );
      break;
  }
  const ok = classify(res);
  check(res, {
    'no 5xx': (r) => r.status < 500,
    '429 has retry-after': (r) => r.status !== 429 || !!r.headers['Retry-After'],
  });
  errorRate.add(!ok);
  latency.add(res.timings.duration);
}
