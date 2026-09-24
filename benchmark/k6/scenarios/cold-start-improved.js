/**
 * K6 Cold Start Benchmark (Improved)
 * 
 * Forces cold starts using unique request identifiers to bypass any caching.
 * Collects individual request data for statistical analysis.
 * 
 * Usage:
 *   k6 run -e ENDPOINT_URL=https://your-worker.workers.dev \
 *          -e RUN_NUMBER=1 \
 *          -e SESSION=morning \
 *          benchmark/k6/scenarios/cold-start-improved.js
 */

import http from 'k6/http';
import { check, sleep } from 'k6';
import { Trend, Counter, Rate } from 'k6/metrics';

// Custom metrics
const coldStartLatency = new Trend('cold_start_latency', true);
const warmLatency = new Trend('warm_latency', true);
const totalRequests = new Counter('total_requests');
const coldStartCount = new Counter('cold_start_count');
const warmCount = new Counter('warm_count');
const errorRate = new Rate('error_rate');

// Configuration
const ENDPOINT_URL = __ENV.ENDPOINT_URL || 'http://localhost:8787';
const ANALYTICS_PATH = '/api/crypto-analytics';
const SYMBOL = __ENV.SYMBOL || 'BTCUSDT';
const INTERVAL = __ENV.INTERVAL || '1h';
const RUN_NUMBER = __ENV.RUN_NUMBER || '1';
const SESSION = __ENV.SESSION || 'default';
const PLATFORM = __ENV.PLATFORM || 'unknown';

// Cold start wait time between iterations (seconds)
const COLD_START_WAIT = parseInt(__ENV.COLD_START_WAIT || '120'); // 2 minutes default
// Iteration count (env-overridable for fast supplemental runs)
const ITERATIONS = parseInt(__ENV.ITERATIONS || '20');

// Collect per-request data
const requestData = [];

export const options = {
  scenarios: {
    cold_start_improved: {
      executor: 'per-vu-iterations',
      vus: 1,
      iterations: ITERATIONS, // env-configurable; default 20 for primary, 5 for supplemental matrix
      maxDuration: '60m',
    },
  },
  thresholds: {
    cold_start_latency: ['p(95)<2000'], // 2s threshold for cold starts
    error_rate: ['rate<0.1'], // Allow up to 10% errors (cold starts can be flaky)
  },
};

export function setup() {
  console.log(`Cold Start Test Configuration:`);
  console.log(`  Endpoint: ${ENDPOINT_URL}`);
  console.log(`  Platform: ${PLATFORM}`);
  console.log(`  Run Number: ${RUN_NUMBER}`);
  console.log(`  Session: ${SESSION}`);
  console.log(`  Wait Between Requests: ${COLD_START_WAIT}s`);
  console.log(`  Symbol: ${SYMBOL}`);
  console.log(`  Interval: ${INTERVAL}`);
  
  return {
    startTime: Date.now(),
    runNumber: RUN_NUMBER,
    session: SESSION,
    platform: PLATFORM,
  };
}

export default function (data) {
  // Generate unique request ID to bypass any caching
  const requestId = `cold-${Date.now()}-${Math.random().toString(36).substring(7)}`;
  const iteration = __ITER + 1;
  
  // Add cache-busting parameters
  const url = `${ENDPOINT_URL}${ANALYTICS_PATH}?symbol=${SYMBOL}&interval=${INTERVAL}&_nocache=${requestId}&_iter=${iteration}`;
  
  const params = {
    headers: {
      'Accept': 'application/json',
      'User-Agent': 'k6-cold-start-benchmark/2.0',
      'Cache-Control': 'no-cache, no-store, must-revalidate',
      'Pragma': 'no-cache',
      'X-Request-ID': requestId,
    },
    tags: {
      scenario: 'cold_start_improved',
      endpoint: ENDPOINT_URL,
      platform: PLATFORM,
      run: RUN_NUMBER,
      session: SESSION,
      iteration: String(iteration),
    },
    timeout: '30s', // Allow longer timeout for cold starts
  };

  console.log(`[Iteration ${iteration}/20] Making request with ID: ${requestId}`);
  
  const startTime = Date.now();
  const response = http.get(url, params);
  const endTime = Date.now();
  
  totalRequests.add(1);

  // Validate response
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
    console.log(`[Iteration ${iteration}] ERROR: Status ${response.status}`);
  } else {
    errorRate.add(0);
    
    try {
      const body = JSON.parse(response.body);
      const isColdStart = body.metadata && body.metadata.coldStart === true;
      
      // Record metrics based on cold start status
      if (isColdStart) {
        coldStartLatency.add(response.timings.duration);
        coldStartCount.add(1);
        console.log(`[Iteration ${iteration}] COLD START: ${response.timings.duration.toFixed(2)}ms`);
      } else {
        warmLatency.add(response.timings.duration);
        warmCount.add(1);
        console.log(`[Iteration ${iteration}] WARM: ${response.timings.duration.toFixed(2)}ms (expected cold)`);
      }
      
      // Store detailed request data for later analysis
      requestData.push({
        iteration,
        requestId,
        timestamp: new Date().toISOString(),
        platform: PLATFORM,
        session: SESSION,
        runNumber: RUN_NUMBER,
        coldStart: isColdStart,
        latency: response.timings.duration,
        serverProcessingTime: body.metadata?.processingTimeMs || 0,
        serverFetchTime: body.metadata?.fetchTimeMs || 0,
        serverComputeTime: body.metadata?.computeTimeMs || 0,
        region: body.metadata?.region || 'unknown',
        status: response.status,
      });
    } catch (e) {
      console.error(`[Iteration ${iteration}] Failed to parse response:`, e.message);
    }
  }

  // Wait before next request to allow instance recycling
  if (iteration < ITERATIONS) {
    console.log(`[Iteration ${iteration}] Waiting ${COLD_START_WAIT}s for cold state...`);
    sleep(COLD_START_WAIT);
  }
}

export function teardown(data) {
  const duration = ((Date.now() - data.startTime) / 1000 / 60).toFixed(2);
  console.log(`\nTest completed in ${duration} minutes`);
  console.log(`Total cold starts detected: Check cold_start_count metric`);
}

export function handleSummary(summaryData) {
  const timestamp = new Date().toISOString().replace(/[:.]/g, '-');
  const platform = PLATFORM !== 'unknown' ? PLATFORM :
                   ENDPOINT_URL.includes('workers.dev') ? 'cloudflare' : 
                   ENDPOINT_URL.includes('vercel.app') ? 'vercel' : 'unknown';
  
  // Enhanced output with per-request data
  const outputData = {
    ...summaryData,
    testMetadata: {
      type: 'cold-start-improved',
      platform,
      runNumber: RUN_NUMBER,
      session: SESSION,
      timestamp: new Date().toISOString(),
      endpoint: ENDPOINT_URL,
      symbol: SYMBOL,
      interval: INTERVAL,
      coldStartWait: COLD_START_WAIT,
    },
    rawLatencies: requestData,
  };
  
  const filename = `cold-start-improved-${platform}-run${RUN_NUMBER}-${SESSION}-${timestamp}.json`;
  
  return {
    [`benchmark/results/${filename}`]: JSON.stringify(outputData, null, 2),
    stdout: textSummary(summaryData),
  };
}

function textSummary(data) {
  const lines = [];
  lines.push('='.repeat(70));
  lines.push('COLD START BENCHMARK RESULTS (IMPROVED)');
  lines.push('='.repeat(70));
  lines.push(`Platform: ${PLATFORM}`);
  lines.push(`Endpoint: ${ENDPOINT_URL}`);
  lines.push(`Run: ${RUN_NUMBER} | Session: ${SESSION}`);
  lines.push(`Symbol: ${SYMBOL} | Interval: ${INTERVAL}`);
  lines.push('-'.repeat(70));
  
  if (data.metrics.cold_start_latency && data.metrics.cold_start_latency.values.count > 0) {
    const cs = data.metrics.cold_start_latency;
    lines.push('Cold Start Latency (instances where coldStart=true):');
    lines.push(`  Count: ${cs.values.count || 0}`);
    lines.push(`  Avg: ${cs.values.avg?.toFixed(2) || 'N/A'} ms`);
    lines.push(`  Min: ${cs.values.min?.toFixed(2) || 'N/A'} ms`);
    lines.push(`  Max: ${cs.values.max?.toFixed(2) || 'N/A'} ms`);
    lines.push(`  P50: ${cs.values['p(50)']?.toFixed(2) || 'N/A'} ms`);
    lines.push(`  P90: ${cs.values['p(90)']?.toFixed(2) || 'N/A'} ms`);
    lines.push(`  P95: ${cs.values['p(95)']?.toFixed(2) || 'N/A'} ms`);
  } else {
    lines.push('Cold Start Latency: No cold starts detected');
  }
  
  lines.push('-'.repeat(70));
  
  if (data.metrics.warm_latency && data.metrics.warm_latency.values.count > 0) {
    const warm = data.metrics.warm_latency;
    lines.push('Warm Latency (instances where coldStart=false):');
    lines.push(`  Count: ${warm.values.count || 0}`);
    lines.push(`  Avg: ${warm.values.avg?.toFixed(2) || 'N/A'} ms`);
  }
  
  lines.push('-'.repeat(70));
  
  if (data.metrics.http_req_duration) {
    const dur = data.metrics.http_req_duration;
    lines.push('HTTP Request Duration (all requests):');
    lines.push(`  Avg: ${dur.values.avg?.toFixed(2) || 'N/A'} ms`);
    lines.push(`  Min: ${dur.values.min?.toFixed(2) || 'N/A'} ms`);
    lines.push(`  Max: ${dur.values.max?.toFixed(2) || 'N/A'} ms`);
    lines.push(`  P95: ${dur.values['p(95)']?.toFixed(2) || 'N/A'} ms`);
  }
  
  lines.push('-'.repeat(70));
  lines.push(`Error Rate: ${((data.metrics.error_rate?.values?.rate || 0) * 100).toFixed(2)}%`);
  lines.push('='.repeat(70));
  
  return lines.join('\n');
}
