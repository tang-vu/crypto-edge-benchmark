// Fast-ramp variant of burst-test for ramp-rate sensitivity (R1.5).
// 0 -> 100 VUs over 15s (sharp), peak 100, 30s cooldown.
// Captures whether burst variance differential persists at rapid ramp.
import http from 'k6/http';
import { check, sleep } from 'k6';
import { Trend, Counter, Rate } from 'k6/metrics';

const latencyByStage = new Trend('latency_by_stage', true);
const throughput = new Counter('successful_requests');
const errorRate = new Rate('error_rate');

const ENDPOINT_URL = __ENV.ENDPOINT_URL || 'http://localhost:8787';
const ANALYTICS_PATH = '/api/crypto-analytics';
const SYMBOL = __ENV.SYMBOL || 'BTCUSDT';
const INTERVAL = __ENV.INTERVAL || '1h';
const RUN_NUMBER = __ENV.RUN_NUMBER || '1';
const PLATFORM = __ENV.PLATFORM || 'unknown';

export const options = {
  scenarios: {
    burst_test_fast: {
      executor: 'ramping-vus',
      startVUs: 0,
      stages: [
        { duration: '15s', target: 100 },  // sharp ramp
        { duration: '30s', target: 0 },    // cooldown
      ],
    },
  },
  thresholds: {
    http_req_duration: ['p(95)<2000', 'p(99)<5000'],
    http_req_failed: ['rate<0.05'],
  },
};

export default function () {
  const url = `${ENDPOINT_URL}${ANALYTICS_PATH}?symbol=${SYMBOL}&interval=${INTERVAL}`;
  const params = {
    headers: { 'Accept': 'application/json', 'User-Agent': 'k6-benchmark/1.0' },
    tags: { scenario: 'burst_test_fast', endpoint: ENDPOINT_URL },
    timeout: '60s',
  };
  const response = http.get(url, params);
  const success = check(response, {
    'status is 200': (r) => r.status === 200,
    'response is valid': (r) => {
      try { return JSON.parse(r.body).success === true; } catch (e) { return false; }
    },
  });
  if (success) {
    throughput.add(1);
    errorRate.add(0);
    latencyByStage.add(response.timings.duration);
  } else {
    errorRate.add(1);
  }
  sleep(Math.random() * 0.1);
}

export function handleSummary(data) {
  const ts = new Date().toISOString().replace(/[:.]/g, '-');
  const platform = PLATFORM !== 'unknown' ? PLATFORM :
                   ENDPOINT_URL.includes('workers.dev') ? 'cloudflare' :
                   ENDPOINT_URL.includes('vercel.app') ? 'vercel' : 'unknown';
  const filename = `burst-test-fast-${platform}-run${RUN_NUMBER}-${ts}.json`;
  return {
    [`benchmark/results/${filename}`]: JSON.stringify({
      ...data,
      testMetadata: { type: 'burst-test-fast', platform, runNumber: RUN_NUMBER, timestamp: new Date().toISOString(), endpoint: ENDPOINT_URL, symbol: SYMBOL, interval: INTERVAL, rampProfile: 'fast-15s-peak100' },
    }, null, 2),
    stdout: `\nBURST-FAST [${platform}] requests=${data.metrics.http_reqs?.values?.count} avg=${data.metrics.http_req_duration?.values?.avg?.toFixed(0)}ms p95=${data.metrics.http_req_duration?.values['p(95)']?.toFixed(0)}ms\n`,
  };
}
