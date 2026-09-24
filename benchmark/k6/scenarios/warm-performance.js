/**
 * K6 Warm Performance Benchmark
 * 
 * Measures latency after instances are warmed up.
 * Runs 1000 sequential requests to get stable metrics.
 * 
 * Usage:
 *   k6 run -e ENDPOINT_URL=https://your-worker.workers.dev benchmark/k6/scenarios/warm-performance.js
 */

import http from 'k6/http';
import { check, sleep } from 'k6';
import { Trend, Counter, Rate } from 'k6/metrics';

// Custom metrics
const processingTime = new Trend('processing_time_ms', true);
const fetchTime = new Trend('fetch_time_ms', true);
const computeTime = new Trend('compute_time_ms', true);
const totalRequests = new Counter('total_requests');
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
    warm_performance: {
      executor: 'per-vu-iterations',
      vus: 1,
      iterations: 1000,
      maxDuration: '30m',
    },
  },
  thresholds: {
    http_req_duration: ['p(50)<200', 'p(95)<500', 'p(99)<1000'],
    error_rate: ['rate<0.01'],
  },
};

// Warmup phase
export function setup() {
  const url = `${ENDPOINT_URL}${ANALYTICS_PATH}?symbol=${SYMBOL}&interval=${INTERVAL}`;
  
  console.log('Warming up endpoint...');
  for (let i = 0; i < 10; i++) {
    http.get(url);
    sleep(0.5);
  }
  console.log('Warmup complete');
  
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
      scenario: 'warm_performance',
      endpoint: ENDPOINT_URL,
    },
  };

  const response = http.get(url, params);
  totalRequests.add(1);

  const success = check(response, {
    'status is 200': (r) => r.status === 200,
    'response has data': (r) => {
      try {
        const body = JSON.parse(r.body);
        return body.success === true;
      } catch (e) {
        return false;
      }
    },
    'not cold start': (r) => {
      try {
        const body = JSON.parse(r.body);
        return body.metadata && body.metadata.coldStart === false;
      } catch (e) {
        return true;
      }
    },
  });

  if (!success) {
    errorRate.add(1);
  } else {
    errorRate.add(0);
    
    try {
      const body = JSON.parse(response.body);
      if (body.metadata) {
        processingTime.add(body.metadata.processingTimeMs);
        fetchTime.add(body.metadata.fetchTimeMs);
        computeTime.add(body.metadata.computeTimeMs);
        
        // Store per-request data for statistical analysis
        requestData.push({
          iteration: __ITER + 1,
          timestamp: new Date().toISOString(),
          latency: response.timings.duration,
          serverProcessingTime: body.metadata.processingTimeMs || 0,
          serverFetchTime: body.metadata.fetchTimeMs || 0,
          serverComputeTime: body.metadata.computeTimeMs || 0,
          region: body.metadata.region || 'unknown',
          coldStart: body.metadata.coldStart || false,
          status: response.status,
        });
      }
    } catch (e) {
      // Ignore parsing errors
    }
  }

  // Small delay between requests
  sleep(0.1);
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
      type: 'warm-performance',
      platform,
      runNumber: RUN_NUMBER,
      timestamp: new Date().toISOString(),
      endpoint: ENDPOINT_URL,
      symbol: SYMBOL,
      interval: INTERVAL,
    },
    rawLatencies: requestData,
  };
  
  const filename = `warm-performance-${platform}-run${RUN_NUMBER}-${timestamp}.json`;
  
  return {
    [`benchmark/results/${filename}`]: JSON.stringify(outputData, null, 2),
    stdout: textSummary(data),
  };
}

function textSummary(data) {
  const lines = [];
  lines.push('='.repeat(60));
  lines.push('WARM PERFORMANCE BENCHMARK RESULTS');
  lines.push('='.repeat(60));
  lines.push(`Endpoint: ${ENDPOINT_URL}`);
  lines.push(`Symbol: ${SYMBOL}`);
  lines.push(`Total Requests: ${data.metrics.total_requests?.values?.count || 'N/A'}`);
  lines.push('-'.repeat(60));
  
  if (data.metrics.http_req_duration) {
    const dur = data.metrics.http_req_duration;
    lines.push('HTTP Request Duration (End-to-End):');
    lines.push(`  Avg: ${dur.values.avg?.toFixed(2) || 'N/A'} ms`);
    lines.push(`  Min: ${dur.values.min?.toFixed(2) || 'N/A'} ms`);
    lines.push(`  Max: ${dur.values.max?.toFixed(2) || 'N/A'} ms`);
    lines.push(`  P50: ${dur.values['p(50)']?.toFixed(2) || 'N/A'} ms`);
    lines.push(`  P90: ${dur.values['p(90)']?.toFixed(2) || 'N/A'} ms`);
    lines.push(`  P95: ${dur.values['p(95)']?.toFixed(2) || 'N/A'} ms`);
    lines.push(`  P99: ${dur.values['p(99)']?.toFixed(2) || 'N/A'} ms`);
  }
  
  lines.push('-'.repeat(60));
  
  if (data.metrics.processing_time_ms) {
    const proc = data.metrics.processing_time_ms;
    lines.push('Server Processing Time:');
    lines.push(`  Avg: ${proc.values.avg?.toFixed(2) || 'N/A'} ms`);
    lines.push(`  P95: ${proc.values['p(95)']?.toFixed(2) || 'N/A'} ms`);
  }
  
  if (data.metrics.fetch_time_ms) {
    const fetch = data.metrics.fetch_time_ms;
    lines.push('API Fetch Time:');
    lines.push(`  Avg: ${fetch.values.avg?.toFixed(2) || 'N/A'} ms`);
  }
  
  if (data.metrics.compute_time_ms) {
    const compute = data.metrics.compute_time_ms;
    lines.push('Compute Time:');
    lines.push(`  Avg: ${compute.values.avg?.toFixed(2) || 'N/A'} ms`);
  }
  
  lines.push('-'.repeat(60));
  lines.push(`Error Rate: ${(data.metrics.error_rate?.values?.rate * 100 || 0).toFixed(2)}%`);
  lines.push('='.repeat(60));
  
  return lines.join('\n');
}
