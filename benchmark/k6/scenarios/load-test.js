/**
 * K6 Load Test Benchmark
 * 
 * Sustained load test with multiple virtual users.
 * Measures throughput and latency under load.
 * 
 * Usage:
 *   k6 run -e ENDPOINT_URL=https://your-worker.workers.dev benchmark/k6/scenarios/load-test.js
 */

import http from 'k6/http';
import { check, sleep } from 'k6';
import { Trend, Counter, Rate } from 'k6/metrics';

// Custom metrics
const processingTime = new Trend('processing_time_ms', true);
const throughput = new Counter('successful_requests');
const errorRate = new Rate('error_rate');

// Configuration
const ENDPOINT_URL = __ENV.ENDPOINT_URL || 'http://localhost:8787';
const ANALYTICS_PATH = '/api/crypto-analytics';
const SYMBOL = __ENV.SYMBOL || 'BTCUSDT';
const INTERVAL = __ENV.INTERVAL || '1h';
const VUS = parseInt(__ENV.VUS) || 10;
const DURATION = __ENV.DURATION || '30s';
const RUN_NUMBER = __ENV.RUN_NUMBER || '1';
const PLATFORM = __ENV.PLATFORM || 'unknown';

// Store per-request data for statistical analysis
const requestData = [];

export const options = {
  scenarios: {
    load_test: {
      executor: 'constant-vus',
      vus: VUS,
      duration: DURATION,
    },
  },
  thresholds: {
    http_req_duration: ['p(95)<500', 'p(99)<1000'],
    http_req_failed: ['rate<0.01'],
    error_rate: ['rate<0.01'],
  },
};

export function setup() {
  // Warmup
  const url = `${ENDPOINT_URL}${ANALYTICS_PATH}?symbol=${SYMBOL}&interval=${INTERVAL}`;
  console.log(`Load Test Configuration:`);
  console.log(`  Endpoint: ${ENDPOINT_URL}`);
  console.log(`  VUs: ${VUS}`);
  console.log(`  Duration: ${DURATION}`);
  
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
      scenario: 'load_test',
      endpoint: ENDPOINT_URL,
    },
    timeout: '30s',
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
    
    try {
      const body = JSON.parse(response.body);
      if (body.metadata?.processingTimeMs) {
        processingTime.add(body.metadata.processingTimeMs);
      }
      
      // Store per-request data for statistical analysis
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
      // Ignore
    }
  } else {
    errorRate.add(1);
  }

  // Think time between requests
  sleep(Math.random() * 0.5 + 0.1); // 100-600ms
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
      type: 'load-test',
      platform,
      runNumber: RUN_NUMBER,
      timestamp: new Date().toISOString(),
      endpoint: ENDPOINT_URL,
      symbol: SYMBOL,
      interval: INTERVAL,
      vus: VUS,
      duration: DURATION,
    },
    rawLatencies: requestData,
  };
  
  const filename = `load-test-${platform}-run${RUN_NUMBER}-${timestamp}.json`;
  
  return {
    [`benchmark/results/${filename}`]: JSON.stringify(outputData, null, 2),
    stdout: textSummary(data),
  };
}

function textSummary(data) {
  const lines = [];
  lines.push('='.repeat(60));
  lines.push('LOAD TEST BENCHMARK RESULTS');
  lines.push('='.repeat(60));
  lines.push(`Endpoint: ${ENDPOINT_URL}`);
  lines.push(`Virtual Users: ${VUS}`);
  lines.push(`Duration: ${DURATION}`);
  lines.push('-'.repeat(60));
  
  if (data.metrics.http_reqs) {
    const reqs = data.metrics.http_reqs;
    lines.push('Throughput:');
    lines.push(`  Total Requests: ${reqs.values.count}`);
    lines.push(`  Requests/sec: ${reqs.values.rate?.toFixed(2) || 'N/A'}`);
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
  lines.push(`Successful Requests: ${data.metrics.successful_requests?.values?.count || 'N/A'}`);
  lines.push(`Error Rate: ${(data.metrics.error_rate?.values?.rate * 100 || 0).toFixed(2)}%`);
  lines.push(`Failed Requests: ${data.metrics.http_req_failed?.values?.passes || 0}`);
  lines.push('='.repeat(60));
  
  return lines.join('\n');
}
