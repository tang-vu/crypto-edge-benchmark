/**
 * Cold Start Benchmark Orchestration Script
 * 
 * Automates cold start testing across multiple platforms and sessions.
 * Implements the protocol from the IEEE paper plan:
 * - 20 iterations per platform per session
 * - 3 sessions (morning/afternoon/evening)
 * - 2 platforms (Cloudflare, Vercel)
 * - Total: 120 cold start measurements
 * 
 * Usage:
 *   node scripts/run-cold-start-benchmark.js --cloudflare <url> --vercel <url>
 *   node scripts/run-cold-start-benchmark.js --cloudflare <url> --vercel <url> --session morning
 */

import { spawn } from 'child_process';
import { mkdir, writeFile, readdir, readFile } from 'fs/promises';
import { join } from 'path';

// ============================================================================
// Configuration
// ============================================================================

const SESSIONS = ['morning', 'afternoon', 'evening'];
const ITERATIONS_PER_SESSION = 20;
const COLD_START_WAIT_SECONDS = 120; // 2 minutes between iterations
const K6_SCRIPT = 'benchmark/k6/scenarios/cold-start-improved.js';
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
    session: null, // null = run all sessions
    dryRun: false,
    symbol: 'BTCUSDT',
    interval: '1h',
    waitTime: COLD_START_WAIT_SECONDS,
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
      case '--session':
      case '-s':
        config.session = args[++i];
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
      case '--wait':
        config.waitTime = parseInt(args[++i]);
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
Cold Start Benchmark Orchestration Script

This script automates the cold start measurement protocol for IEEE paper research.
Protocol: 20 iterations × 3 sessions × 2 platforms = 120 measurements

Usage:
  node scripts/run-cold-start-benchmark.js [options]

Options:
  --cloudflare, -cf <url>   Cloudflare Worker endpoint URL
  --vercel, -v <url>        Vercel Edge endpoint URL
  --session, -s <name>      Run specific session (morning, afternoon, evening)
  --wait <seconds>          Wait time between iterations (default: 120)
  --symbol <symbol>         Crypto symbol (default: BTCUSDT)
  --interval <interval>     Time interval (default: 1h)
  --dry-run                 Print plan without executing
  --help, -h                Show this help

Examples:
  # Run all sessions for both platforms
  node scripts/run-cold-start-benchmark.js \\
    --cloudflare https://crypto-analytics-worker.xxx.workers.dev \\
    --vercel https://vercel-edge-xxx.vercel.app

  # Run only morning session
  node scripts/run-cold-start-benchmark.js \\
    --cloudflare https://crypto-analytics-worker.xxx.workers.dev \\
    --session morning

  # Preview execution plan
  node scripts/run-cold-start-benchmark.js \\
    --cloudflare https://example.workers.dev \\
    --vercel https://example.vercel.app \\
    --dry-run

Estimated Time:
  Per platform per session: ~40 minutes (20 iterations × 2 min wait)
  All sessions, both platforms: ~4 hours
  Single session, single platform: ~40 minutes
`);
}

// ============================================================================
// K6 Runner
// ============================================================================

async function runK6ColdStart(platform, endpoint, session, runNumber, config) {
  const envVars = {
    ENDPOINT_URL: endpoint,
    PLATFORM: platform,
    SESSION: session,
    RUN_NUMBER: String(runNumber),
    SYMBOL: config.symbol,
    INTERVAL: config.interval,
    COLD_START_WAIT: String(config.waitTime),
  };

  console.log(`\n${'─'.repeat(70)}`);
  console.log(`▶ Starting Cold Start Test`);
  console.log(`  Platform: ${platform}`);
  console.log(`  Session: ${session}`);
  console.log(`  Run: ${runNumber}`);
  console.log(`  Endpoint: ${endpoint}`);
  console.log(`${'─'.repeat(70)}\n`);

  return new Promise((resolve, reject) => {
    const k6 = spawn('k6', ['run', K6_SCRIPT], {
      env: { ...process.env, ...envVars },
      stdio: 'inherit',
      // Note: shell: true removed to prevent shell injection
    });

    k6.on('close', (code) => {
      resolve({
        success: code === 0,
        platform,
        session,
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

async function aggregateColdStartResults() {
  console.log('\n' + '═'.repeat(70));
  console.log('AGGREGATING COLD START RESULTS');
  console.log('═'.repeat(70));

  const files = await readdir(RESULTS_DIR);
  const coldStartFiles = files.filter(f => f.startsWith('cold-start-improved-'));
  
  const allResults = {
    cloudflare: [],
    vercel: [],
  };

  for (const file of coldStartFiles) {
    try {
      const content = await readFile(join(RESULTS_DIR, file), 'utf-8');
      const data = JSON.parse(content);
      
      const platform = data.testMetadata?.platform || 'unknown';
      const rawLatencies = data.rawLatencies || [];
      
      if (platform === 'cloudflare') {
        allResults.cloudflare.push(...rawLatencies);
      } else if (platform === 'vercel') {
        allResults.vercel.push(...rawLatencies);
      }
    } catch (e) {
      console.warn(`Warning: Could not parse ${file}: ${e.message}`);
    }
  }

  // Calculate statistics
  const stats = {};
  for (const platform of ['cloudflare', 'vercel']) {
    const data = allResults[platform];
    const coldStarts = data.filter(d => d.coldStart === true);
    const warmStarts = data.filter(d => d.coldStart === false);
    
    if (coldStarts.length > 0) {
      const latencies = coldStarts.map(d => d.latency).sort((a, b) => a - b);
      stats[platform] = {
        coldStartCount: coldStarts.length,
        warmStartCount: warmStarts.length,
        totalMeasurements: data.length,
        coldStartRate: (coldStarts.length / data.length * 100).toFixed(1) + '%',
        mean: (latencies.reduce((a, b) => a + b, 0) / latencies.length).toFixed(2),
        min: latencies[0]?.toFixed(2),
        max: latencies[latencies.length - 1]?.toFixed(2),
        p50: percentile(latencies, 50)?.toFixed(2),
        p90: percentile(latencies, 90)?.toFixed(2),
        p95: percentile(latencies, 95)?.toFixed(2),
        p99: percentile(latencies, 99)?.toFixed(2),
        rawLatencies: latencies,
      };
    }
  }

  // Save aggregated results
  const aggregatedPath = join(RESULTS_DIR, `cold-start-aggregated-${Date.now()}.json`);
  await writeFile(aggregatedPath, JSON.stringify({ stats, allResults }, null, 2));
  console.log(`\nAggregated results saved to: ${aggregatedPath}`);

  // Print summary
  console.log('\n' + '─'.repeat(70));
  console.log('COLD START STATISTICS SUMMARY');
  console.log('─'.repeat(70));
  
  for (const platform of ['cloudflare', 'vercel']) {
    if (stats[platform]) {
      const s = stats[platform];
      console.log(`\n${platform.toUpperCase()}:`);
      console.log(`  Measurements: ${s.totalMeasurements} (${s.coldStartCount} cold, ${s.warmStartCount} warm)`);
      console.log(`  Cold Start Rate: ${s.coldStartRate}`);
      console.log(`  Mean Latency: ${s.mean} ms`);
      console.log(`  Min: ${s.min} ms | Max: ${s.max} ms`);
      console.log(`  P50: ${s.p50} ms | P90: ${s.p90} ms | P95: ${s.p95} ms`);
    }
  }

  return stats;
}

function percentile(arr, p) {
  if (arr.length === 0) return null;
  const index = Math.ceil(arr.length * (p / 100)) - 1;
  return arr[Math.max(0, index)];
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

  const sessions = config.session ? [config.session] : SESSIONS;
  
  const totalRuns = platforms.length * sessions.length;
  const estimatedMinutes = totalRuns * ITERATIONS_PER_SESSION * config.waitTime / 60;

  console.log('\n' + '═'.repeat(70));
  console.log('COLD START BENCHMARK ORCHESTRATION');
  console.log('═'.repeat(70));
  console.log(`\nExecution Plan:`);
  console.log(`  Platforms: ${platforms.map(p => p.name).join(', ')}`);
  console.log(`  Sessions: ${sessions.join(', ')}`);
  console.log(`  Iterations per session: ${ITERATIONS_PER_SESSION}`);
  console.log(`  Wait between iterations: ${config.waitTime}s`);
  console.log(`  Total k6 runs: ${totalRuns}`);
  console.log(`  Total measurements: ${totalRuns * ITERATIONS_PER_SESSION}`);
  console.log(`  Estimated time: ${estimatedMinutes.toFixed(0)} minutes (~${(estimatedMinutes/60).toFixed(1)} hours)`);
  console.log(`\nSymbol: ${config.symbol} | Interval: ${config.interval}`);

  if (config.dryRun) {
    console.log('\n[DRY RUN] Would execute:');
    let runNumber = 1;
    for (const session of sessions) {
      for (const platform of platforms) {
        console.log(`  Run ${runNumber}: ${platform.name} - ${session}`);
        runNumber++;
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
  let runNumber = 1;

  for (const session of sessions) {
    console.log(`\n${'▓'.repeat(70)}`);
    console.log(`SESSION: ${session.toUpperCase()}`);
    console.log(`${'▓'.repeat(70)}`);

    for (const platform of platforms) {
      try {
        const result = await runK6ColdStart(
          platform.name,
          platform.url,
          session,
          runNumber,
          config
        );
        results.push(result);
        
        if (result.success) {
          console.log(`\n✓ Run ${runNumber} completed successfully`);
        } else {
          console.log(`\n✗ Run ${runNumber} failed with exit code ${result.exitCode}`);
        }
      } catch (err) {
        console.error(`\n✗ Run ${runNumber} error: ${err.message}`);
        results.push({
          success: false,
          platform: platform.name,
          session,
          runNumber,
          error: err.message,
        });
      }
      
      runNumber++;
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
  
  console.log(`\nResults:`);
  for (const result of results) {
    const status = result.success ? '✓' : '✗';
    console.log(`  ${status} ${result.platform} - ${result.session} (Run ${result.runNumber})`);
  }
  
  console.log(`\nSuccessful: ${successful}/${results.length}`);
  if (failed > 0) {
    console.log(`Failed: ${failed}/${results.length}`);
  }

  // Aggregate results
  try {
    await aggregateColdStartResults();
  } catch (e) {
    console.error('Warning: Could not aggregate results:', e.message);
  }

  // Save execution summary
  const summaryPath = join(RESULTS_DIR, `cold-start-execution-summary-${Date.now()}.json`);
  await writeFile(summaryPath, JSON.stringify({
    timestamp: new Date().toISOString(),
    durationMinutes,
    config: {
      symbol: config.symbol,
      interval: config.interval,
      waitTime: config.waitTime,
      sessions,
    },
    platforms: platforms.map(p => ({ name: p.name, url: p.url })),
    results,
  }, null, 2));
  
  console.log(`\nExecution summary saved to: ${summaryPath}`);

  console.log('\n' + '═'.repeat(70));
  console.log('Next Steps:');
  console.log('  1. Review individual result files in benchmark/results/');
  console.log('  2. Run statistical analysis: python benchmark/analysis/analyze.py');
  console.log('  3. Generate figures: python benchmark/analysis/visualize_paper.py');
  console.log('═'.repeat(70) + '\n');
}

main().catch(console.error);
