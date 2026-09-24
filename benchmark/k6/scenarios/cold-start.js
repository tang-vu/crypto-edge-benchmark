/**
 * K6 Cold Start Benchmark
 * 
 * Measures cold start latency by deploying fresh instances
 * and making immediate requests.
 * 
 * Usage:
 *   k6 run -e ENDPOINT_URL=https://your-worker.workers.dev benchmark/k6/scenarios/cold-start.js
 */

import http from 'k6/http';
import { check, sleep } from 'k6';
import { Trend, Counter, Rate } from 'k6/metrics';

// Custom metrics
const coldStartLatency = new Trend('cold_start_latency', true);
const warmLatency = new Trend('warm_latency', true);
const totalRequests = new Counter('total_requests');
const errorRate = new Rate('error_rate');

// Configuration
const ENDPOINT_URL = __ENV.ENDPOINT_URL || 'http://localhost:8787';
const ANALYTICS_PATH = '/api/crypto-analytics';
const SYMBOL = __ENV.SYMBOL || 'BTCUSDT';
const INTERVAL = __ENV.INTERVAL || '1h';

export const options = {
  scenarios: {
    cold_start_test: {
      executor: 'per-vu-iterations',
      vus: 1,
      iterations: 10,
      maxDuration: '30m',
    },
  },
  thresholds: {
    cold_start_latency: ['p(95)<1000'],
    error_rate: ['rate<0.05'],
  },
};

export default function () {
  const url = `${ENDPOINT_URL}${ANALYTICS_PATH}?symbol=${SYMBOL}&interval=${INTERVAL}`;
  
  const params = {
    headers: {
      'Accept': 'application/json',
      'User-Agent': 'k6-benchmark/1.0',
    },
    tags: {
      scenario: 'cold_start',
      endpoint: ENDPOINT_URL,
    },
  };

  // Make request
  const response = http.get(url, params);
  totalRequests.add(1);

  // Check response
  const success = check(response, {
    'status is 200': (r) => r.status === 200,
    'response has data': (r) => {
      try {
        const body = JSON.parse(r.body);
        return body.success === true && body.data !== undefined;
      } catch (e) {
        return false;
      }
    },
    'has metadata': (r) => {
      try {
        const body = JSON.parse(r.body);
        return body.metadata !== undefined;
      } catch (e) {
        return false;
      }
    },
  });

  if (!success) {
    errorRate.add(1);
  } else {
    errorRate.add(0);
    
    // Extract timing from response
    try {
      const body = JSON.parse(response.body);
      if (body.metadata) {
        if (body.metadata.coldStart) {
          coldStartLatency.add(response.timings.duration);
        } else {
          warmLatency.add(response.timings.duration);
        }
      }
    } catch (e) {
      console.error('Failed to parse response:', e);
    }
  }

  // Wait 5 minutes between requests to allow cold start
  // In real testing, you'd redeploy or wait for instance recycling
  sleep(300); // 5 minutes
}

export function handleSummary(data) {
  const timestamp = new Date().toISOString().replace(/[:.]/g, '-');
  const platform = ENDPOINT_URL.includes('workers.dev') ? 'cloudflare' : 
                   ENDPOINT_URL.includes('amazonaws.com') ? 'lambda' : 'unknown';
  
  return {
    [`benchmark/results/cold-start-${platform}-${timestamp}.json`]: JSON.stringify(data, null, 2),
    stdout: textSummary(data, { indent: '  ', enableColors: true }),
  };
}

function textSummary(data, options) {
  const lines = [];
  lines.push('='.repeat(60));
  lines.push('COLD START BENCHMARK RESULTS');
  lines.push('='.repeat(60));
  lines.push(`Endpoint: ${ENDPOINT_URL}`);
  lines.push(`Symbol: ${SYMBOL}`);
  lines.push(`Interval: ${INTERVAL}`);
  lines.push('-'.repeat(60));
  
  if (data.metrics.cold_start_latency) {
    const cs = data.metrics.cold_start_latency;
    lines.push('Cold Start Latency:');
    lines.push(`  Avg: ${cs.values.avg?.toFixed(2) || 'N/A'} ms`);
    lines.push(`  Min: ${cs.values.min?.toFixed(2) || 'N/A'} ms`);
    lines.push(`  Max: ${cs.values.max?.toFixed(2) || 'N/A'} ms`);
    lines.push(`  P95: ${cs.values['p(95)']?.toFixed(2) || 'N/A'} ms`);
  }
  
  if (data.metrics.http_req_duration) {
    const dur = data.metrics.http_req_duration;
    lines.push('HTTP Request Duration:');
    lines.push(`  Avg: ${dur.values.avg?.toFixed(2) || 'N/A'} ms`);
    lines.push(`  P50: ${dur.values['p(50)']?.toFixed(2) || 'N/A'} ms`);
    lines.push(`  P95: ${dur.values['p(95)']?.toFixed(2) || 'N/A'} ms`);
    lines.push(`  P99: ${dur.values['p(99)']?.toFixed(2) || 'N/A'} ms`);
  }
  
  lines.push('='.repeat(60));
  return lines.join('\n');
}
