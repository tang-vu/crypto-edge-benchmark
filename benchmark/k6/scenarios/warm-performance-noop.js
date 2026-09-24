/**
 * K6 Warm Performance Benchmark — No-Op Endpoint
 *
 * Measures steady-state latency of the minimal no-op handler.
 * Run this against both CF and Vercel no-op endpoints; delta vs.
 * full warm-performance run = application-layer overhead.
 *
 * Protocol: 1000 requests × n=3 runs, 1 VU (sequential), warm state.
 * Matches warm-performance.js parameters exactly for valid comparison.
 *
 * Usage:
 *   k6 run -e ENDPOINT_URL=https://crypto-analytics-noop.8ndwvxvrgt.workers.dev \
 *          -e PLATFORM=cloudflare -e RUN_NUMBER=1 \
 *          benchmark/k6/scenarios/warm-performance-noop.js
 */

import http from 'k6/http';
import { check, sleep } from 'k6';
import { Trend, Counter, Rate } from 'k6/metrics';

const noopLatency   = new Trend('noop_latency_ms', true);
const totalRequests = new Counter('total_requests');
const errorRate     = new Rate('error_rate');

const ENDPOINT_URL = __ENV.ENDPOINT_URL || 'http://localhost:8787';
const NOOP_PATH    = '/api/noop';
const SYMBOL       = __ENV.SYMBOL       || 'BTCUSDT';
const INTERVAL     = __ENV.INTERVAL     || '1h';
const RUN_NUMBER   = __ENV.RUN_NUMBER   || '1';
const PLATFORM     = __ENV.PLATFORM     || 'unknown';

const requestData = [];

export const options = {
  scenarios: {
    warm_noop: {
      executor:    'per-vu-iterations',
      vus:         1,
      iterations:  1000,
      maxDuration: '30m',
    },
  },
  thresholds: {
    http_req_duration: ['p(50)<100', 'p(95)<300', 'p(99)<600'],
    error_rate:        ['rate<0.01'],
  },
};

export function setup() {
  const url = `${ENDPOINT_URL}${NOOP_PATH}?symbol=${SYMBOL}&interval=${INTERVAL}`;
  console.log(`[warm-performance-noop] Warming up: ${url}`);
  for (let i = 0; i < 10; i++) {
    http.get(url);
    sleep(0.5);
  }
  console.log('[warm-performance-noop] Warmup complete');
  return { startTime: Date.now() };
}

export default function () {
  const url = `${ENDPOINT_URL}${NOOP_PATH}?symbol=${SYMBOL}&interval=${INTERVAL}`;

  const params = {
    headers: {
      'Accept':     'application/json',
      'User-Agent': 'k6-benchmark/1.0',
    },
    timeout: '30s',
  };

  const response = http.get(url, params);
  totalRequests.add(1);

  const success = check(response, {
    'status is 200': (r) => r.status === 200,
    'ok is true':    (r) => {
      try { return JSON.parse(r.body).ok === true; }
      catch (e) { return false; }
    },
  });

  if (success) {
    errorRate.add(0);
    noopLatency.add(response.timings.duration);

    try {
      const body = JSON.parse(response.body);
      requestData.push({
        iteration:      __ITER + 1,
        timestamp:      new Date().toISOString(),
        latency_ms:     response.timings.duration,
        ttfb_ms:        response.timings.waiting,
        send_ms:        response.timings.sending,
        recv_ms:        response.timings.receiving,
        processing_ms:  body.processingTimeMs || 0,
        cold_start:     body.coldStart || false,
        region:         body.region    || 'unknown',
        status:         response.status,
        // Header capture for routing verification
        cf_ray:      response.headers['Cf-Ray']      || null,
        x_vercel_id: response.headers['X-Vercel-Id'] || null,
      });
    } catch (e) {
      requestData.push({
        iteration:  __ITER + 1,
        timestamp:  new Date().toISOString(),
        latency_ms: response.timings.duration,
        ttfb_ms:    response.timings.waiting,
        status:     response.status,
      });
    }
  } else {
    errorRate.add(1);
  }

  sleep(0.1);
}

export function handleSummary(data) {
  const timestamp = new Date().toISOString().replace(/[:.]/g, '-');
  const platform  = PLATFORM !== 'unknown' ? PLATFORM
    : ENDPOINT_URL.includes('workers.dev') ? 'cloudflare'
    : ENDPOINT_URL.includes('vercel.app')  ? 'vercel'
    : 'unknown';

  const outputData = {
    ...data,
    testMetadata: {
      type:         'warm-noop',
      platform,
      runNumber:    RUN_NUMBER,
      timestamp:    new Date().toISOString(),
      endpoint:     ENDPOINT_URL,
      symbol:       SYMBOL,
      interval:     INTERVAL,
      totalSamples: requestData.length,
    },
    rawLatencies: requestData,
  };

  const filename  = `warm-noop-${platform}-run${RUN_NUMBER}-${timestamp}.json`;
  const outDir    = `benchmark/results/r1-revision/local/${platform}/noop/`;

  return {
    [`${outDir}${filename}`]: JSON.stringify(outputData, null, 2),
    stdout: _textSummary(data, platform),
  };
}

function _textSummary(data, platform) {
  const lines = [];
  lines.push('='.repeat(60));
  lines.push(`WARM NO-OP BENCHMARK — ${platform.toUpperCase()}`);
  lines.push('='.repeat(60));
  lines.push(`Endpoint: ${ENDPOINT_URL}`);
  if (data.metrics.http_req_duration) {
    const dur = data.metrics.http_req_duration;
    lines.push('Latency (no-op handler):');
    lines.push(`  Avg: ${dur.values.avg?.toFixed(2) || 'N/A'} ms`);
    lines.push(`  P50: ${dur.values['p(50)']?.toFixed(2) || 'N/A'} ms`);
    lines.push(`  P95: ${dur.values['p(95)']?.toFixed(2) || 'N/A'} ms`);
    lines.push(`  P99: ${dur.values['p(99)']?.toFixed(2) || 'N/A'} ms`);
  }
  lines.push('='.repeat(60));
  return lines.join('\n');
}
