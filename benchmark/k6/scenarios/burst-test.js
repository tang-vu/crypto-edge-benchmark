/**
 * K6 Burst Test Benchmark
 * 
 * Tests system behavior under sudden traffic spikes.
 * Simulates real-world scenarios where traffic varies dramatically.
 * 
 * Usage:
 *   k6 run -e ENDPOINT_URL=https://your-worker.workers.dev benchmark/k6/scenarios/burst-test.js
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

// Store per-request data for statistical analysis
const requestData = [];

export const options = {
  scenarios: {
    burst_test: {
      executor: 'ramping-vus',
      startVUs: 0,
      stages: [
        { duration: '30s', target: 10 },   // Ramp up to 10 users
        { duration: '1m', target: 100 },   // Spike to 100 users
        { duration: '30s', target: 200 },  // Burst to 200 users
        { duration: '1m', target: 50 },    // Scale down
        { duration: '30s', target: 0 },    // Ramp down to 0
      ],
    },
  },
  thresholds: {
    http_req_duration: ['p(95)<1000', 'p(99)<2000'],
    http_req_failed: ['rate<0.05'],
    error_rate: ['rate<0.05'],
  },
};

export function setup() {
  console.log('Burst Test Configuration:');
  console.log(`  Endpoint: ${ENDPOINT_URL}`);
  console.log('  Stages:');
  console.log('    0s-30s:   0 -> 10 VUs');
  console.log('    30s-1m30s: 10 -> 100 VUs');
  console.log('    1m30s-2m: 100 -> 200 VUs (BURST)');
  console.log('    2m-3m:    200 -> 50 VUs');
  console.log('    3m-3m30s: 50 -> 0 VUs');
  
  // Warmup
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
      'Accept': 'application/json',
      'User-Agent': 'k6-benchmark/1.0',
    },
    tags: {
      scenario: 'burst_test',
      endpoint: ENDPOINT_URL,
    },
    timeout: '60s',
  };

  const response = http.get(url, params);

  const success = check(response, {
    'status is 200': (r) => r.status === 200,
    'response is valid': (r) => {
      try {
        const body = JSON.parse(r.body);
        return body.success === true;
      } catch (e) {
        return false;
      }
    },
  });

  if (success) {
    throughput.add(1);
    errorRate.add(0);
    latencyByStage.add(response.timings.duration);
    
    // Store per-request data for statistical analysis
    try {
      const body = JSON.parse(response.body);
      requestData.push({
        timestamp: new Date().toISOString(),
        latency: response.timings.duration,
        serverProcessingTime: body.metadata?.processingTimeMs || 0,
        region: body.metadata?.region || 'unknown',
        coldStart: body.metadata?.coldStart || false,
        status: response.status,
        vu: __VU,
        iter: __ITER,
      });
    } catch (e) {
      requestData.push({
        timestamp: new Date().toISOString(),
        latency: response.timings.duration,
        status: response.status,
        vu: __VU,
        iter: __ITER,
      });
    }
  } else {
    errorRate.add(1);
  }

  // Minimal sleep to maximize load
  sleep(Math.random() * 0.2);
}

export function handleSummary(data) {
  const timestamp = new Date().toISOString().replace(/[:.]/g, '-');
  const platform = PLATFORM !== 'unknown' ? PLATFORM :
                   ENDPOINT_URL.includes('workers.dev') ? 'cloudflare' : 
                   ENDPOINT_URL.includes('vercel.app') ? 'vercel' :
                   ENDPOINT_URL.includes('amazonaws.com') ? 'lambda' : 'unknown';
  
  // Enhanced output with per-request data and test metadata
  const outputData = {
    ...data,
    testMetadata: {
      type: 'burst-test',
      platform,
      runNumber: RUN_NUMBER,
      timestamp: new Date().toISOString(),
      endpoint: ENDPOINT_URL,
      symbol: SYMBOL,
      interval: INTERVAL,
    },
    rawLatencies: requestData,
  };
  
  const filename = `burst-test-${platform}-run${RUN_NUMBER}-${timestamp}.json`;
  
  return {
    [`benchmark/results/${filename}`]: JSON.stringify(outputData, null, 2),
    stdout: textSummary(data),
  };
}

function textSummary(data) {
  const lines = [];
  lines.push('='.repeat(60));
  lines.push('BURST TEST BENCHMARK RESULTS');
  lines.push('='.repeat(60));
  lines.push(`Endpoint: ${ENDPOINT_URL}`);
  lines.push('Pattern: Ramp -> Spike -> Burst -> Scale Down');
  lines.push('-'.repeat(60));
  
  if (data.metrics.http_reqs) {
    const reqs = data.metrics.http_reqs;
    lines.push('Throughput:');
    lines.push(`  Total Requests: ${reqs.values.count}`);
    lines.push(`  Requests/sec (avg): ${reqs.values.rate?.toFixed(2) || 'N/A'}`);
  }
  
  if (data.metrics.http_req_duration) {
    const dur = data.metrics.http_req_duration;
    lines.push('Latency:');
    lines.push(`  Avg: ${dur.values.avg?.toFixed(2) || 'N/A'} ms`);
    lines.push(`  Min: ${dur.values.min?.toFixed(2) || 'N/A'} ms`);
    lines.push(`  Max: ${dur.values.max?.toFixed(2) || 'N/A'} ms`);
    lines.push(`  P50: ${dur.values['p(50)']?.toFixed(2) || 'N/A'} ms`);
    lines.push(`  P90: ${dur.values['p(90)']?.toFixed(2) || 'N/A'} ms`);
    lines.push(`  P95: ${dur.values['p(95)']?.toFixed(2) || 'N/A'} ms`);
    lines.push(`  P99: ${dur.values['p(99)']?.toFixed(2) || 'N/A'} ms`);
  }
  
  lines.push('-'.repeat(60));
  lines.push('Scaling Behavior:');
  lines.push(`  Successful Requests: ${data.metrics.successful_requests?.values?.count || 'N/A'}`);
  lines.push(`  Error Rate: ${(data.metrics.error_rate?.values?.rate * 100 || 0).toFixed(2)}%`);
  lines.push(`  Max Latency During Burst: ${data.metrics.http_req_duration?.values?.max?.toFixed(2) || 'N/A'} ms`);
  lines.push('='.repeat(60));
  
  return lines.join('\n');
}
