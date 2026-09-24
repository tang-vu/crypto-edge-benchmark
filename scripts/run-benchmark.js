/**
 * Benchmark Runner Script
 * 
 * Automates running all benchmark scenarios against all endpoints.
 * 
 * Usage:
 *   node scripts/run-benchmark.js --cloudflare https://your-worker.workers.dev --lambda https://your-api.amazonaws.com
 */

import { spawn } from 'child_process';
import { mkdir, writeFile } from 'fs/promises';
import { join } from 'path';

const SCENARIOS = [
  {
    name: 'cold-start',
    script: 'benchmark/k6/scenarios/cold-start.js',
    description: 'Cold start latency test'
  },
  {
    name: 'warm-performance',
    script: 'benchmark/k6/scenarios/warm-performance.js',
    description: 'Warm performance test'
  },
  {
    name: 'load-test',
    script: 'benchmark/k6/scenarios/load-test.js',
    description: 'Sustained load test'
  },
  {
    name: 'burst-test',
    script: 'benchmark/k6/scenarios/burst-test.js',
    description: 'Burst/spike test'
  }
];

function parseArgs() {
  const args = process.argv.slice(2);
  const config = {
    cloudflare: null,
    lambda: null,
    scenarios: ['all'],
    symbol: 'BTCUSDT',
    interval: '1h',
    skipColdStart: false
  };

  for (let i = 0; i < args.length; i++) {
    switch (args[i]) {
      case '--cloudflare':
      case '-cf':
        config.cloudflare = args[++i];
        break;
      case '--lambda':
      case '-l':
        config.lambda = args[++i];
        break;
      case '--scenario':
      case '-s':
        config.scenarios = [args[++i]];
        break;
      case '--symbol':
        config.symbol = args[++i];
        break;
      case '--interval':
        config.interval = args[++i];
        break;
      case '--skip-cold-start':
        config.skipColdStart = true;
        break;
      case '--help':
      case '-h':
        printHelp();
        process.exit(0);
    }
  }

  return config;
}

function printHelp() {
  console.log(`
Crypto Edge Benchmark Runner

Usage:
  node scripts/run-benchmark.js [options]

Options:
  --cloudflare, -cf <url>   Cloudflare Worker endpoint URL
  --lambda, -l <url>        AWS Lambda endpoint URL
  --scenario, -s <name>     Run specific scenario (cold-start, warm-performance, load-test, burst-test)
  --symbol <symbol>         Crypto symbol to test (default: BTCUSDT)
  --interval <interval>     Time interval (default: 1h)
  --skip-cold-start         Skip cold start test (it takes a long time)
  --help, -h                Show this help

Examples:
  node scripts/run-benchmark.js --cloudflare https://crypto-analytics.workers.dev --lambda https://xxx.execute-api.us-east-1.amazonaws.com/dev
  node scripts/run-benchmark.js -cf https://crypto-analytics.workers.dev -s warm-performance
`);
}

async function runK6(scenario, endpoint, platform, symbol, interval) {
  const envVars = {
    ENDPOINT_URL: endpoint,
    SYMBOL: symbol,
    INTERVAL: interval
  };

  console.log(`\n${'='.repeat(60)}`);
  console.log(`Running: ${scenario.description}`);
  console.log(`Platform: ${platform}`);
  console.log(`Endpoint: ${endpoint}`);
  console.log(`${'='.repeat(60)}\n`);

  return new Promise((resolve, reject) => {
    const k6 = spawn('k6', ['run', scenario.script], {
      env: { ...process.env, ...envVars },
      stdio: 'inherit',
      shell: true
    });

    k6.on('close', (code) => {
      if (code === 0) {
        resolve({ success: true, scenario: scenario.name, platform });
      } else {
        resolve({ success: false, scenario: scenario.name, platform, code });
      }
    });

    k6.on('error', (err) => {
      reject(err);
    });
  });
}

async function ensureResultsDir() {
  await mkdir('benchmark/results', { recursive: true });
}

async function main() {
  const config = parseArgs();

  if (!config.cloudflare && !config.lambda) {
    console.error('Error: At least one endpoint URL is required.');
    console.error('Use --cloudflare <url> and/or --lambda <url>');
    console.error('Run with --help for more information.');
    process.exit(1);
  }

  await ensureResultsDir();

  const endpoints = [];
  if (config.cloudflare) {
    endpoints.push({ url: config.cloudflare, platform: 'cloudflare' });
  }
  if (config.lambda) {
    endpoints.push({ url: config.lambda, platform: 'lambda' });
  }

  let scenarios = SCENARIOS;
  if (config.scenarios[0] !== 'all') {
    scenarios = SCENARIOS.filter(s => config.scenarios.includes(s.name));
  }
  if (config.skipColdStart) {
    scenarios = scenarios.filter(s => s.name !== 'cold-start');
  }

  console.log('\n' + '='.repeat(60));
  console.log('CRYPTO EDGE BENCHMARK SUITE');
  console.log('='.repeat(60));
  console.log(`\nEndpoints to test: ${endpoints.length}`);
  console.log(`Scenarios to run: ${scenarios.length}`);
  console.log(`Symbol: ${config.symbol}`);
  console.log(`Interval: ${config.interval}`);
  console.log('\n');

  const results = [];
  const startTime = Date.now();

  for (const scenario of scenarios) {
    for (const endpoint of endpoints) {
      try {
        const result = await runK6(
          scenario,
          endpoint.url,
          endpoint.platform,
          config.symbol,
          config.interval
        );
        results.push(result);
      } catch (err) {
        console.error(`Error running ${scenario.name} on ${endpoint.platform}:`, err.message);
        results.push({
          success: false,
          scenario: scenario.name,
          platform: endpoint.platform,
          error: err.message
        });
      }
    }
  }

  const endTime = Date.now();
  const duration = ((endTime - startTime) / 1000 / 60).toFixed(2);

  // Summary
  console.log('\n' + '='.repeat(60));
  console.log('BENCHMARK SUMMARY');
  console.log('='.repeat(60));
  console.log(`Total duration: ${duration} minutes`);
  console.log(`\nResults:`);

  const successful = results.filter(r => r.success).length;
  const failed = results.filter(r => !r.success).length;

  for (const result of results) {
    const status = result.success ? '✓' : '✗';
    console.log(`  ${status} ${result.platform} - ${result.scenario}`);
  }

  console.log(`\nSuccessful: ${successful}/${results.length}`);
  if (failed > 0) {
    console.log(`Failed: ${failed}/${results.length}`);
  }

  // Save summary
  const summary = {
    timestamp: new Date().toISOString(),
    duration: duration,
    config: {
      symbol: config.symbol,
      interval: config.interval,
      endpoints: endpoints.map(e => ({ platform: e.platform, url: e.url }))
    },
    results
  };

  const summaryPath = join('benchmark/results', `benchmark-summary-${Date.now()}.json`);
  await writeFile(summaryPath, JSON.stringify(summary, null, 2));
  console.log(`\nSummary saved to: ${summaryPath}`);

  console.log('\n' + '='.repeat(60));
  console.log('Next steps:');
  console.log('  1. Run: python benchmark/analysis/analyze.py');
  console.log('  2. Run: python benchmark/analysis/visualize.py');
  console.log('='.repeat(60) + '\n');
}

main().catch(console.error);
