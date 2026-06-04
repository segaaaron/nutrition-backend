// k6 baseline smoke — NOVA backend (item #30A).
//
// Purpose: low-RPS sanity check for local dev / pre-staging smoke.
// 5 RPS sustained 30s across read endpoints + health probes.
//
// Usage:
//   k6 run -e BASE_URL=http://localhost:8000 -e TOKEN=<bearer> \
//     tests/load/k6_baseline_smoke.js
//
// Thresholds:
//   - p95 < 500ms
//   - error rate < 1%
//
// Stages: ramp-up 10s → sustain 30s @ 5 RPS → ramp-down 10s.

import http from 'k6/http';
import { check } from 'k6';
import { Rate, Trend } from 'k6/metrics';

const BASE = __ENV.BASE_URL || 'http://localhost:8000';
const TOKEN = __ENV.TOKEN || '';

const errorRate = new Rate('errors');
const readLatency = new Trend('read_latency');

export const options = {
  scenarios: {
    smoke: {
      executor: 'ramping-arrival-rate',
      startRate: 0,
      timeUnit: '1s',
      preAllocatedVUs: 10,
      maxVUs: 30,
      stages: [
        { target: 5, duration: '10s' },   // ramp-up
        { target: 5, duration: '30s' },   // sustain
        { target: 0, duration: '10s' },   // ramp-down
      ],
    },
  },
  thresholds: {
    http_req_duration: ['p(95)<500'],
    errors: ['rate<0.01'],
    http_req_failed: ['rate<0.01'],
  },
};

const authHeaders = () => ({
  headers: {
    Authorization: TOKEN ? `Bearer ${TOKEN}` : '',
    'Content-Type': 'application/json',
  },
});

const endpoints = [
  { name: 'healthz', url: `${BASE}/healthz`, authed: false },
  { name: 'readyz', url: `${BASE}/readyz`, authed: false },
  { name: 'plan_me', url: `${BASE}/v1/plan/me`, authed: true },
  { name: 'recipes_search', url: `${BASE}/v1/recipes/search?q=arroz`, authed: true },
];

export default function () {
  const ep = endpoints[Math.floor(Math.random() * endpoints.length)];
  const params = ep.authed ? authHeaders() : {};
  const res = http.get(ep.url, params);
  const ok = check(res, {
    [`${ep.name}: status acceptable`]: (r) => r.status < 500,
  });
  errorRate.add(!ok);
  readLatency.add(res.timings.duration);
}
