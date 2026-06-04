// k6 baseline load scenarios for NOVA backend.
//
// Usage:
//   k6 run \
//     -e BASE_URL=https://api.ms-tech-stack.cloud \
//     -e TOKEN=<bearer> \
//     tests/load/k6_baseline.js
//
// Scenarios:
//   - steady_100rps_10m   60% read / 30% write logs / 10% plan+coach
//   - spike_500rps_30s    burst surge — validates autoscale + circuit breakers
//   - soak_50rps_2h       sustained — leak detection, p99 stability
//
// Thresholds:
//   - p95 < 500ms (excluding photo upload + coach SSE)
//   - p99 < 1s
//   - error rate < 0.5%
//
// IMPORTANT: file is documented only — NOT executed in CI. Requires running
// stack with seeded test users + tokens (see scripts/seed_load_users.py
// follow-up).

import http from 'k6/http';
import { check, sleep } from 'k6';
import { Trend, Rate } from 'k6/metrics';

const BASE = __ENV.BASE_URL || 'http://localhost:8000';
const TOKEN = __ENV.TOKEN || '';

const errorRate = new Rate('errors');
const readLatency = new Trend('read_latency');
const writeLatency = new Trend('write_latency');

export const options = {
  scenarios: {
    steady_100rps_10m: {
      executor: 'constant-arrival-rate',
      rate: 100, timeUnit: '1s',
      duration: '10m',
      preAllocatedVUs: 100, maxVUs: 300,
      exec: 'mix',
    },
    spike_500rps_30s: {
      executor: 'constant-arrival-rate',
      rate: 500, timeUnit: '1s',
      duration: '30s',
      preAllocatedVUs: 400, maxVUs: 800,
      exec: 'mix',
      startTime: '11m',
    },
    soak_50rps_2h: {
      executor: 'constant-arrival-rate',
      rate: 50, timeUnit: '1s',
      duration: '2h',
      preAllocatedVUs: 60, maxVUs: 150,
      exec: 'mix',
      startTime: '12m',
    },
  },
  thresholds: {
    'http_req_duration{kind:read}': ['p(95)<500', 'p(99)<1000'],
    'http_req_duration{kind:write}': ['p(95)<800', 'p(99)<1500'],
    'errors': ['rate<0.005'],
  },
};

const headers = () => ({
  'Authorization': `Bearer ${TOKEN}`,
  'Content-Type': 'application/json',
});

function get(path) {
  const r = http.get(`${BASE}${path}`, { headers: headers(), tags: { kind: 'read' } });
  readLatency.add(r.timings.duration);
  errorRate.add(r.status >= 400);
  return r;
}

function post(path, body) {
  const r = http.post(`${BASE}${path}`, JSON.stringify(body),
    { headers: headers(), tags: { kind: 'write' } });
  writeLatency.add(r.timings.duration);
  errorRate.add(r.status >= 400);
  return r;
}

export function mix() {
  const roll = Math.random();
  if (roll < 0.6) {
    // 60% reads — dashboard + lists
    const choices = [
      '/logs/food/totals/today',
      '/logs/food?limit=20',
      '/logs/water/today',
      '/gamification/streak',
      '/gamification/achievements',
      '/me/subscription',
      '/progress',
      '/fasting/active',
    ];
    const path = choices[Math.floor(Math.random() * choices.length)];
    const r = get(path);
    check(r, { 'read_ok': (x) => x.status === 200 });
  } else if (roll < 0.9) {
    // 30% writes — logs
    const path = '/logs/water';
    const r = post(path, { ml: 250 });
    check(r, { 'write_ok': (x) => x.status === 201 || x.status === 200 });
  } else {
    // 10% plan + coach
    const r = get('/plans/current');
    check(r, { 'plan_ok': (x) => x.status === 200 || x.status === 404 });
  }
  sleep(0.05);
}
