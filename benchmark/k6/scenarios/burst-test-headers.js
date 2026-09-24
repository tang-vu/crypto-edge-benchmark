/**
 * K6 Burst Test with Response Header Capture
 *
 * Variant of burst-test.js that additionally captures CF-Ray and X-Vercel-Id
 * response headers per request. This enables isolate-level distribution analysis
 * (R1.4 telemetry requirement): CF datacenter colo distribution + Vercel lambda
 * instance affinity / isolate reuse patterns.
 *
 * Usage:
 *   k6 run -e ENDPOINT_URL=https://crypto-analytics-worker.8ndwvxvrgt.workers.dev \
 *          -e PLATFORM=cloudflare -e RUN_NUMBER=1 \
 *          --out csv=benchmark/results/r1-revision/local/cloudflare/burst-headers/burst-cloudflare-headers-run1.csv \
 *          benchmark/k6/scenarios/burst-test-headers.js
 *
 * Header semantics:
 *   CF-Ray:      "<ray_id>-<COLO>"  e.g. "8b3f4c2a1d9e0123-SIN"
 *   X-Vercel-Id: "<region>::<lambda_id>-<seq>" e.g. "iad1::abc12-1234"
 *
 * Output JSON includes rawLatencies[] with cf_ray + x_vercel_id per request.
 * Null values are preserved (graceful if headers absent on some VUs).
 */

import http from 'k6/http';
import { check, sleep } from 'k6';
import { Trend, Counter, Rate } from 'k6/metrics';

// Custom metrics
const latencyByStage = new Trend('latency_by_stage', true);
const throughput = new Counter('successful_requests');
const errorRate = new Rate('error_rate');

// Configuration
const ENDPOINT_URL = __ENV.ENDPOINT_URL || 'http://localhost:8787';
const ANALYTICS_PATH = '/api/crypto-analytics';
const SYMBOL = __ENV.SYMBOL || 'BTCUSDT';
const INTERVAL = __ENV.INTERVAL || '1h';
const RUN_NUMBER = __ENV.RUN_NUMBER || '1';
const PLATFORM = __ENV.PLATFORM || 'unknown';

// NOTE: k6 VU isolation — requestData[] cannot aggregate across VUs in handleSummary.
// Header data is emitted via console.log('HDR:...') per request instead.
// See burst-test-headers.js usage notes and raw-trace-isolate-analyzer.py.

export const options = {
  scenarios: {
    burst_headers: {
      executor: 'ramping-vus',
      startVUs: 0,
      stages: [
        { duration: '30s', target: 10 },    // ramp_up:  0 → 10 VU
        { duration: '1m',  target: 100 },   // spike:   10 → 100 VU
        { duration: '30s', target: 200 },   // peak_hold: 100 → 200 VU
        { duration: '1m',  target: 50 },    // ramp_down: 200 → 50 VU
        { duration: '30s', target: 0 },     // cooldown:  50 → 0 VU
      ],
    },
  },
  thresholds: {
    http_req_duration: ['p(95)<1500', 'p(99)<3000'],
    http_req_failed:   ['rate<0.05'],
    error_rate:        ['rate<0.05'],
  },
};

export function setup() {
  console.log('[burst-test-headers] Configuration:');
  console.log(`  Endpoint:  ${ENDPOINT_URL}`);
  console.log(`  Platform:  ${PLATFORM}`);
  console.log(`  Run:       ${RUN_NUMBER}`);
  console.log('  Stages: 30s ramp + 1m spike + 30s peak + 1m down + 30s cool');

  // Warmup — 5 requests to ensure instance is warm before header capture
  const url = `${ENDPOINT_URL}${ANALYTICS_PATH}?symbol=${SYMBOL}&interval=${INTERVAL}`;
  for (let i = 0; i < 5; i++) {
    http.get(url);
    sleep(0.2);
  }

  return { startTime: Date.now() };
}

export default function () {
  const url = `${ENDPOINT_URL}${ANALYTICS_PATH}?symbol=${SYMBOL}&interval=${INTERVAL}`;

  const params = {
    headers: {
      'Accept':     'application/json',
      'User-Agent': 'k6-benchmark-headers/1.0',
    },
    tags: {
      scenario: 'burst_headers',
      endpoint: ENDPOINT_URL,
    },
    timeout: '60s',
    // k6 does NOT expose response headers in --out csv by default.
    // We read them from response.headers in the default function and
    // store them in requestData[] for handleSummary JSON output.
  };

  const response = http.get(url, params);
  const ts = new Date().toISOString();

  // Extract provider-specific routing headers
  // CF-Ray format:       "<hex>-<COLO>"   (e.g. "8b3f-SIN")
  // X-Vercel-Id format:  "<region>::<id>" (e.g. "iad1::abc-1")
  // Headers may be absent on error responses; default to null.
  const cfRay      = response.headers['Cf-Ray']      || null;
  const xVercelId  = response.headers['X-Vercel-Id'] || null;

  const success = check(response, {
    'status is 200': (r) => r.status === 200,
    'response valid': (r) => {
      try { return JSON.parse(r.body).success === true; }
      catch (e) { return false; }
    },
  });

  if (success) {
    throughput.add(1);
    errorRate.add(0);
    latencyByStage.add(response.timings.duration);
  } else {
    errorRate.add(1);
  }

  // Emit per-request header record to stdout as NDJSON.
  // k6 runs each VU in an isolated JS context — in-memory arrays (requestData[])
  // are NOT shared across VUs and are empty in handleSummary. Instead we use
  // console.log to write one JSON line per request; the caller redirects stdout
  // to a file and the Python analyzer filters lines prefixed "HDR:".
  try {
    const body = JSON.parse(response.body);
    console.log('HDR:' + JSON.stringify({
      ts,
      vu:           __VU,
      iter:         __ITER,
      lat:          response.timings.duration,
      ttfb:         response.timings.waiting,
      status:       response.status,
      cf_ray:       cfRay,
      x_vercel_id:  xVercelId,
      region:       body.metadata?.region            || null,
      proc_ms:      body.metadata?.processingTimeMs  || null,
      cold:         body.metadata?.coldStart         || false,
    }));
  } catch (e) {
    console.log('HDR:' + JSON.stringify({
      ts,
      vu:          __VU,
      iter:        __ITER,
      lat:         response.timings.duration,
      ttfb:        response.timings.waiting,
      status:      response.status,
      cf_ray:      cfRay,
      x_vercel_id: xVercelId,
      region:      null,
      proc_ms:     null,
      cold:        null,
    }));
  }

  // Minimal sleep to maintain burst pressure
  sleep(Math.random() * 0.2);
}

export function handleSummary(data) {
  const timestamp = new Date().toISOString().replace(/[:.]/g, '-');
  const platform = PLATFORM !== 'unknown' ? PLATFORM
    : ENDPOINT_URL.includes('workers.dev') ? 'cloudflare'
    : ENDPOINT_URL.includes('vercel.app')  ? 'vercel'
    : 'unknown';

  // rawLatencies not populated here (VU isolation); header data is in stdout HDR: lines.
  const outputData = {
    ...data,
    testMetadata: {
      type:      'burst-headers',
      platform,
      runNumber: RUN_NUMBER,
      timestamp: new Date().toISOString(),
      endpoint:  ENDPOINT_URL,
      symbol:    SYMBOL,
      interval:  INTERVAL,
      note:      'Per-request header data in stdout HDR: lines; parse with raw-trace-isolate-analyzer.py',
    },
  };

  const filename = `burst-headers-${platform}-run${RUN_NUMBER}-${timestamp}.json`;
  const outDir   = `benchmark/results/r1-revision/local/${platform}/burst-headers/`;

  return {
    [`${outDir}${filename}`]: JSON.stringify(outputData, null, 2),
    stdout: _textSummary(data),
  };
}

// ---------------------------------------------------------------------------
// Text summary helper
// ---------------------------------------------------------------------------

function _textSummary(data) {
  const lines = [];
  lines.push('='.repeat(60));
  lines.push('BURST-TEST WITH HEADERS — RESULTS');
  lines.push('='.repeat(60));
  lines.push(`Endpoint: ${ENDPOINT_URL}`);
  lines.push('Header data: parse HDR: lines from k6 stdout log file.');
  lines.push('Use: raw-trace-isolate-analyzer.py --log <stdout_file>');

  if (data.metrics.http_req_duration) {
    const dur = data.metrics.http_req_duration;
    lines.push('\nLatency:');
    lines.push(`  Total requests: ${data.metrics.http_reqs?.values?.count || 'N/A'}`);
    lines.push(`  Avg: ${dur.values.avg?.toFixed(2) || 'N/A'} ms`);
    lines.push(`  P95: ${dur.values['p(95)']?.toFixed(2) || 'N/A'} ms`);
    lines.push(`  P99: ${dur.values['p(99)']?.toFixed(2) || 'N/A'} ms`);
  }

  lines.push('='.repeat(60));
  return lines.join('\n');
}
