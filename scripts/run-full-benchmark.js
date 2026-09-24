/**
 * Full Benchmark Orchestration Script
 * 
 * Runs all benchmark scenarios with multiple runs for statistical analysis.
 * Protocol: 5 runs × 4 scenarios × 2 platforms = 40 test runs
 * 
 * Usage:
 *   node scripts/run-full-benchmark.js --cloudflare <url> --vercel <url>
 *   node scripts/run-full-benchmark.js --cloudflare <url> --vercel <url> --runs 5
 */

import { spawn } from 'child_process';
import { mkdir, writeFile, readdir, readFile } from 'fs/promises';
import { join } from 'path';

// ============================================================================
// Configuration
// ============================================================================

const SCENARIOS = [
  {
    name: 'warm-performance',
    script: 'benchmark/k6/scenarios/warm-performance.js',
    description: 'Warm latency test (1000 sequential requests)',
    estimatedMinutes: 3,
  },
  {
    name: 'load-test',
    script: 'benchmark/k6/scenarios/load-test.js',
    description: 'Sustained load test (10 VUs, 30s)',
    estimatedMinutes: 1,
  },
  {
    name: 'burst-test',
    script: 'benchmark/k6/scenarios/burst-test.js',
    description: 'Burst/spike test (0→100 VUs)',
    estimatedMinutes: 2,
  },
];

const DEFAULT_RUNS_PER_SCENARIO = 5;
const INTER_RUN_DELAY_MS = 60 * 1000; // 1 minute between runs
const INTER_SCENARIO_DELAY_MS = 120 * 1000; // 2 minutes between scenarios
const RESULTS_DIR = 'benchmark/results';

// ============================================================================
// URL Validation
// ============================================================================

function validateUrl(url, name) {
  try {
    new URL(url);
    return true;
  } catch {
    console.error(`Error: Invalid URL for ${name}: ${url}`);
    return false;
  }
}

// ============================================================================
// Argument Parsing
// ============================================================================

function parseArgs() {
  const args = process.argv.slice(2);
  const config = {
    cloudflare: null,
    vercel: null,
    runs: DEFAULT_RUNS_PER_SCENARIO,
    scenarios: null, // null = run all
    dryRun: false,
    symbol: 'BTCUSDT',
    interval: '1h',
    skipWarmup: false,
  };

  for (let i = 0; i < args.length; i++) {
    switch (args[i]) {
      case '--cloudflare':
      case '-cf':
        config.cloudflare = args[++i];
        break;
      case '--vercel':
      case '-v':
        config.vercel = args[++i];
        break;
      case '--runs':
      case '-r':
        config.runs = parseInt(args[++i]);
        break;
      case '--scenario':
      case '-s':
        config.scenarios = [args[++i]];
        break;
      case '--dry-run':
        config.dryRun = true;
        break;
      case '--symbol':
        config.symbol = args[++i];
        break;
      case '--interval':
        config.interval = args[++i];
        break;
      case '--skip-warmup':
        config.skipWarmup = true;
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
Full Benchmark Orchestration Script

Runs all benchmark scenarios with multiple runs for statistical analysis.
Default: 5 runs × 3 scenarios × 2 platforms = 30 test runs

Usage:
  node scripts/run-full-benchmark.js [options]

Options:
  --cloudflare, -cf <url>   Cloudflare Worker endpoint URL
  --vercel, -v <url>        Vercel Edge endpoint URL
  --runs, -r <number>       Runs per scenario per platform (default: 5)
  --scenario, -s <name>     Run specific scenario only
  --skip-warmup             Skip warmup phase
  --symbol <symbol>         Crypto symbol (default: BTCUSDT)
  --interval <interval>     Time interval (default: 1h)
  --dry-run                 Print plan without executing
  --help, -h                Show this help

Scenarios:
  warm-performance          1000 sequential requests, ~3 min
  load-test                 10 VUs sustained for 30s, ~1 min
  burst-test                Traffic spike 0→100 VUs, ~2 min

Examples:
  # Run full benchmark suite (5 runs each)
  node scripts/run-full-benchmark.js \\
    --cloudflare https://crypto-analytics-worker.xxx.workers.dev \\
    --vercel https://vercel-edge-xxx.vercel.app

  # Run 10 iterations of warm-performance only
  node scripts/run-full-benchmark.js \\
    --cloudflare https://crypto-analytics-worker.xxx.workers.dev \\
    --runs 10 --scenario warm-performance

  # Preview execution plan
  node scripts/run-full-benchmark.js \\
    --cloudflare https://example.workers.dev \\
    --vercel https://example.vercel.app \\
    --dry-run

Estimated Time (5 runs, 2 platforms):
  warm-performance: ~30 min
  load-test: ~10 min
  burst-test: ~20 min
  Total: ~1 hour
`);
}

// ============================================================================
// Sleep Utility
// ============================================================================

function sleep(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

// ============================================================================
// K6 Runner
// ============================================================================

async function runK6(scenario, endpoint, platform, runNumber, config) {
  const envVars = {
    ENDPOINT_URL: endpoint,
    PLATFORM: platform,
    RUN_NUMBER: String(runNumber),
    SCENARIO: scenario.name,
    SYMBOL: config.symbol,
    INTERVAL: config.interval,
  };

  console.log(`\n${'─'.repeat(70)}`);
  console.log(`▶ ${scenario.description}`);
  console.log(`  Platform: ${platform} | Run: ${runNumber}/${config.runs}`);
  console.log(`  Endpoint: ${endpoint}`);
  console.log(`${'─'.repeat(70)}\n`);

  return new Promise((resolve, reject) => {
    const k6 = spawn('k6', ['run', scenario.script], {
      env: { ...process.env, ...envVars },
      stdio: 'inherit',
      // Note: shell: true removed to prevent shell injection
    });

    k6.on('close', (code) => {
      resolve({
        success: code === 0,
        platform,
        scenario: scenario.name,
        runNumber,
        exitCode: code,
      });
    });

    k6.on('error', (err) => {
      reject(err);
    });
  });
}

// ============================================================================
// Results Aggregation
// ============================================================================

async function aggregateResults() {
  console.log('\n' + '═'.repeat(70));
  console.log('AGGREGATING BENCHMARK RESULTS');
  console.log('═'.repeat(70));

  const files = await readdir(RESULTS_DIR);
  
  const aggregated = {
    timestamp: new Date().toISOString(),
    scenarios: {},
  };

  for (const scenario of SCENARIOS) {
    aggregated.scenarios[scenario.name] = {
      cloudflare: { runs: [], metrics: {} },
      vercel: { runs: [], metrics: {} },
    };
  }

  for (const file of files) {
    if (!file.endsWith('.json') || file.startsWith('aggregated-') || file.startsWith('benchmark-summary')) {
      continue;
    }

    try {
      const content = await readFile(join(RESULTS_DIR, file), 'utf-8');
      const data = JSON.parse(content);
      
      // Determine scenario and platform from filename
      const scenarioMatch = SCENARIOS.find(s => file.includes(s.name.replace('-', '')));
      const platform = file.includes('cloudflare') ? 'cloudflare' : 
                       file.includes('vercel') ? 'vercel' : null;
      
      if (!scenarioMatch || !platform) continue;

      // Extract key metrics
      const metrics = data.metrics || {};
      const httpDuration = metrics.http_req_duration?.values || {};
      
      aggregated.scenarios[scenarioMatch.name][platform].runs.push({
        file,
        avg: httpDuration.avg,
        min: httpDuration.min,
        max: httpDuration.max,
        p50: httpDuration['p(50)'],
        p90: httpDuration['p(90)'],
        p95: httpDuration['p(95)'],
        p99: httpDuration['p(99)'],
        totalRequests: metrics.total_requests?.values?.count || metrics.http_reqs?.values?.count,
        errorRate: metrics.error_rate?.values?.rate,
      });
    } catch (e) {
      // Skip files that can't be parsed
    }
  }

  // Calculate aggregate statistics
  for (const scenarioName of Object.keys(aggregated.scenarios)) {
    for (const platform of ['cloudflare', 'vercel']) {
      const runs = aggregated.scenarios[scenarioName][platform].runs;
      if (runs.length > 0) {
        const avgLatencies = runs.map(r => r.avg).filter(v => v != null);
        const p95Latencies = runs.map(r => r.p95).filter(v => v != null);
        
        if (avgLatencies.length > 0) {
          aggregated.scenarios[scenarioName][platform].metrics = {
            runs: runs.length,
            avgLatency: {
              mean: mean(avgLatencies),
              std: std(avgLatencies),
              min: Math.min(...avgLatencies),
              max: Math.max(...avgLatencies),
            },
            p95Latency: {
              mean: mean(p95Latencies),
              std: std(p95Latencies),
              min: Math.min(...p95Latencies),
              max: Math.max(...p95Latencies),
            },
          };
        }
      }
    }
  }

  // Save aggregated results
  const aggregatedPath = join(RESULTS_DIR, `aggregated-full-benchmark-${Date.now()}.json`);
  await writeFile(aggregatedPath, JSON.stringify(aggregated, null, 2));
  console.log(`\nAggregated results saved to: ${aggregatedPath}`);

  // Print summary table
  printSummaryTable(aggregated);

  return aggregated;
}

function mean(arr) {
  if (arr.length === 0) return 0;
  return arr.reduce((a, b) => a + b, 0) / arr.length;
}

function std(arr) {
  if (arr.length < 2) return 0;
  const m = mean(arr);
  const variance = arr.reduce((sum, val) => sum + Math.pow(val - m, 2), 0) / (arr.length - 1);
  return Math.sqrt(variance);
}

function printSummaryTable(aggregated) {
  console.log('\n' + '─'.repeat(70));
  console.log('BENCHMARK STATISTICS SUMMARY');
  console.log('─'.repeat(70));
  
  console.log('\n%-25s %-20s %-20s'.replace(/%(-?\d+)s/g, (_, n) => '%-' + n + 's')
    .replace(/%(-?\d+)s/g, ''), 'Scenario', 'Cloudflare', 'Vercel');
  console.log('─'.repeat(70));

  for (const scenarioName of Object.keys(aggregated.scenarios)) {
    const cf = aggregated.scenarios[scenarioName].cloudflare.metrics;
    const vercel = aggregated.scenarios[scenarioName].vercel.metrics;
    
    const cfStr = cf.avgLatency ? 
      `${cf.avgLatency.mean.toFixed(1)}±${cf.avgLatency.std.toFixed(1)}ms (n=${cf.runs})` : 
      'No data';
    const vercelStr = vercel.avgLatency ? 
      `${vercel.avgLatency.mean.toFixed(1)}±${vercel.avgLatency.std.toFixed(1)}ms (n=${vercel.runs})` : 
      'No data';
    
    console.log(`${scenarioName.padEnd(25)} ${cfStr.padEnd(20)} ${vercelStr}`);
  }
  
  console.log('─'.repeat(70));
}

// ============================================================================
// Main Execution
// ============================================================================

async function main() {
  const config = parseArgs();

  // Validate inputs
  if (!config.cloudflare && !config.vercel) {
    console.error('Error: At least one endpoint URL is required.');
    console.error('Use --cloudflare <url> and/or --vercel <url>');
    process.exit(1);
  }

  // Validate URLs
  if (config.cloudflare && !validateUrl(config.cloudflare, 'cloudflare')) {
    process.exit(1);
  }
  if (config.vercel && !validateUrl(config.vercel, 'vercel')) {
    process.exit(1);
  }

  // Ensure results directory exists
  await mkdir(RESULTS_DIR, { recursive: true });

  // Build execution plan
  const platforms = [];
  if (config.cloudflare) {
    platforms.push({ name: 'cloudflare', url: config.cloudflare });
  }
  if (config.vercel) {
    platforms.push({ name: 'vercel', url: config.vercel });
  }

  const scenarios = config.scenarios 
    ? SCENARIOS.filter(s => config.scenarios.includes(s.name))
    : SCENARIOS;

  const totalRuns = platforms.length * scenarios.length * config.runs;
  const estimatedMinutes = scenarios.reduce((sum, s) => sum + s.estimatedMinutes, 0) 
    * platforms.length * config.runs 
    + (totalRuns - 1) * (INTER_RUN_DELAY_MS / 60000);

  console.log('\n' + '═'.repeat(70));
  console.log('FULL BENCHMARK ORCHESTRATION');
  console.log('═'.repeat(70));
  console.log(`\nExecution Plan:`);
  console.log(`  Platforms: ${platforms.map(p => p.name).join(', ')}`);
  console.log(`  Scenarios: ${scenarios.map(s => s.name).join(', ')}`);
  console.log(`  Runs per scenario: ${config.runs}`);
  console.log(`  Total k6 runs: ${totalRuns}`);
  console.log(`  Estimated time: ${estimatedMinutes.toFixed(0)} minutes`);
  console.log(`\nSymbol: ${config.symbol} | Interval: ${config.interval}`);

  if (config.dryRun) {
    console.log('\n[DRY RUN] Would execute:');
    let runNumber = 1;
    for (const scenario of scenarios) {
      for (let run = 1; run <= config.runs; run++) {
        for (const platform of platforms) {
          console.log(`  ${runNumber}: ${scenario.name} - ${platform.name} (run ${run}/${config.runs})`);
          runNumber++;
        }
      }
    }
    console.log('\nNo tests executed (dry run mode)');
    return;
  }

  console.log('\n' + '═'.repeat(70));
  console.log('STARTING BENCHMARK EXECUTION');
  console.log('═'.repeat(70));

  const results = [];
  const startTime = Date.now();
  let completedRuns = 0;

  for (const scenario of scenarios) {
    console.log(`\n${'▓'.repeat(70)}`);
    console.log(`SCENARIO: ${scenario.name.toUpperCase()}`);
    console.log(`${scenario.description}`);
    console.log(`${'▓'.repeat(70)}`);

    for (let run = 1; run <= config.runs; run++) {
      for (const platform of platforms) {
        try {
          const result = await runK6(scenario, platform.url, platform.name, run, config);
          results.push(result);
          
          if (result.success) {
            console.log(`\n✓ ${scenario.name} - ${platform.name} (run ${run}) completed`);
          } else {
            console.log(`\n✗ ${scenario.name} - ${platform.name} (run ${run}) failed`);
          }
        } catch (err) {
          console.error(`\n✗ ${scenario.name} - ${platform.name} (run ${run}) error: ${err.message}`);
          results.push({
            success: false,
            platform: platform.name,
            scenario: scenario.name,
            runNumber: run,
            error: err.message,
          });
        }
        
        completedRuns++;
        const remaining = totalRuns - completedRuns;
        
        if (remaining > 0) {
          console.log(`\n⏱ Progress: ${completedRuns}/${totalRuns} runs complete`);
          console.log(`  Waiting 60s before next run...`);
          await sleep(INTER_RUN_DELAY_MS);
        }
      }
    }

    // Extra delay between scenarios
    if (scenario !== scenarios[scenarios.length - 1]) {
      console.log(`\n⏱ Waiting 2 minutes before next scenario...`);
      await sleep(INTER_SCENARIO_DELAY_MS);
    }
  }

  const endTime = Date.now();
  const durationMinutes = ((endTime - startTime) / 1000 / 60).toFixed(2);

  // Summary
  console.log('\n' + '═'.repeat(70));
  console.log('EXECUTION SUMMARY');
  console.log('═'.repeat(70));
  console.log(`\nTotal duration: ${durationMinutes} minutes`);
  
  const successful = results.filter(r => r.success).length;
  const failed = results.filter(r => !r.success).length;
  
  console.log(`\nSuccessful: ${successful}/${results.length}`);
  if (failed > 0) {
    console.log(`Failed: ${failed}/${results.length}`);
  }

  // Aggregate results
  try {
    await aggregateResults();
  } catch (e) {
    console.error('Warning: Could not aggregate results:', e.message);
  }

  // Save execution summary
  const summaryPath = join(RESULTS_DIR, `benchmark-execution-summary-${Date.now()}.json`);
  await writeFile(summaryPath, JSON.stringify({
    timestamp: new Date().toISOString(),
    durationMinutes,
    config: {
      symbol: config.symbol,
      interval: config.interval,
      runsPerScenario: config.runs,
    },
    platforms: platforms.map(p => ({ name: p.name, url: p.url })),
    scenarios: scenarios.map(s => s.name),
    results,
  }, null, 2));
  
  console.log(`\nExecution summary saved to: ${summaryPath}`);

  console.log('\n' + '═'.repeat(70));
  console.log('Next Steps:');
  console.log('  1. Run statistical analysis: python benchmark/analysis/statistical_analysis.py');
  console.log('  2. Generate figures: python benchmark/analysis/visualize_paper.py');
  console.log('  3. Update paper sections with new results');
  console.log('═'.repeat(70) + '\n');
}

main().catch(console.error);
