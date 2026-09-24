# System Architecture

> **Version:** 1.0.0  
> **Last Updated:** January 16, 2026

## High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           BENCHMARK CLIENT                               │
│                                                                          │
│  ┌──────────────┐    ┌─────────────────────────────────────────────────┐ │
│  │    k6 Load   │───▶│  HTTP Requests (GET /api/crypto-analytics)      │ │
│  │    Tester    │◀───│  JSON Responses + Timing Metrics                │ │
│  └──────────────┘    └─────────────────────────────────────────────────┘ │
│         │                                                                │
│         ▼                                                                │
│  ┌──────────────┐                                                        │
│  │   Results    │───▶  benchmark/results/*.json                         │
│  │   Export     │                                                        │
│  └──────────────┘                                                        │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                    ┌───────────────┴───────────────┐
                    ▼                               ▼
┌───────────────────────────────────┐   ┌───────────────────────────────────┐
│      CLOUDFLARE WORKERS           │   │      VERCEL EDGE FUNCTIONS        │
│                                   │   │                                   │
│  ┌─────────────────────────────┐  │   │  ┌─────────────────────────────┐  │
│  │     Cloudflare Edge         │  │   │  │     Vercel Edge Network     │  │
│  │     (300+ PoPs globally)    │  │   │  │                             │  │
│  └─────────────────────────────┘  │   │  └─────────────────────────────┘  │
│              │                    │   │              │                    │
│              ▼                    │   │              ▼                    │
│  ┌─────────────────────────────┐  │   │  ┌─────────────────────────────┐  │
│  │     V8 Isolate Runtime      │  │   │  │     V8 Isolate Runtime      │  │
│  │     (Lightweight, fast)     │  │   │  │     (Node.js compat)        │  │
│  └─────────────────────────────┘  │   │  └─────────────────────────────┘  │
│              │                    │   │              │                    │
│              ▼                    │   │              ▼                    │
│  ┌─────────────────────────────┐  │   │  ┌─────────────────────────────┐  │
│  │   crypto-analytics-worker   │  │   │  │   api/crypto-analytics.ts   │  │
│  │   (imports shared pkg)      │  │   │  │   (self-contained)          │  │
│  └─────────────────────────────┘  │   │  └─────────────────────────────┘  │
│                                   │   │                                   │
│  Region: HKG (Hong Kong)         │   │  Region: hkg1 (Hong Kong)        │
└───────────────────────────────────┘   └───────────────────────────────────┘
```

## Platform Comparison

| Aspect | Cloudflare Workers | Vercel Edge |
|--------|-------------------|-------------|
| **Runtime** | V8 Isolates | V8 Isolates (Node.js compat) |
| **Edge Network** | 300+ PoPs | Vercel Edge Network |
| **Cold Start** | ~0-5ms | ~5-15ms |
| **Max Execution** | 30s (paid), 10ms (free) | 30s |
| **Memory Limit** | 128MB | 128MB |
| **Deployment** | Wrangler CLI | Vercel CLI |
| **Package Support** | npm (bundled) | npm (with limits) |
| **Region Detection** | `request.cf.colo` | `x-vercel-id` header |

## Request Flow

### 1. Client Request

```
Client (k6) ──HTTP GET──▶ Edge CDN ──Route──▶ Edge Function
```

### 2. Edge Function Processing

```
┌────────────────────────────────────────────────────────────────┐
│                     EDGE FUNCTION                              │
│                                                                │
│  1. Parse Request                                              │
│     └─▶ Extract query params (symbol, interval)               │
│                                                                │
│  2. Validate Input                                             │
│     └─▶ isValidSymbol(), isValidInterval()                    │
│                                                                │
│  3. Create Context                                             │
│     └─▶ { requestId, startTime, coldStart, region, platform } │
│                                                                │
│  4. Process Analytics                                          │
│     ├─▶ Fetch ticker data (mock or real)                      │
│     ├─▶ Fetch OHLC data                                       │
│     ├─▶ Calculate VWAP                                        │
│     └─▶ Build response                                        │
│                                                                │
│  5. Return JSON Response                                       │
│     └─▶ { success, data, metadata }                           │
└────────────────────────────────────────────────────────────────┘
```

### 3. Timing Breakdown

```
Request Start ─────────────────────────────────────────▶ Response End
    │                                                        │
    ├── Network Latency (client → edge) ──┐                 │
    │                                     │                 │
    │   ┌─────────────────────────────────┴──────────────┐  │
    │   │         EDGE PROCESSING                        │  │
    │   │                                                │  │
    │   │  ├─ Cold Start (if applicable): 0-15ms        │  │
    │   │  ├─ Data Fetch (mock): ~0.1ms                 │  │
    │   │  ├─ VWAP Calculation: ~0.01ms                 │  │
    │   │  └─ Response Serialization: ~0.1ms            │  │
    │   │                                                │  │
    │   │  Total Processing: ~1-5ms                     │  │
    │   └────────────────────────────────────────────────┘  │
    │                                                       │
    └── Network Latency (edge → client) ────────────────────┘
```

## Shared Package Architecture

### Module Structure

```
packages/shared/
├── src/
│   ├── index.ts           # Barrel exports (public API)
│   ├── types.ts           # Type definitions
│   ├── crypto-analytics.ts # VWAP, SMA, EMA calculations
│   └── price-fetcher.ts   # Data fetching + mock mode
└── dist/                  # Compiled output
```

### Dependency Graph

```
┌─────────────────┐
│    index.ts     │  ◀── Public API (barrel exports)
└────────┬────────┘
         │ re-exports
         ▼
┌─────────────────────────────────────────────────┐
│                                                 │
│  ┌───────────────┐    ┌───────────────────────┐ │
│  │   types.ts    │◀───│  crypto-analytics.ts  │ │
│  │   (no deps)   │    │                       │ │
│  └───────────────┘    └───────────┬───────────┘ │
│         ▲                         │             │
│         │                         │ imports     │
│         │                         ▼             │
│         │             ┌───────────────────────┐ │
│         └─────────────│   price-fetcher.ts    │ │
│                       │                       │ │
│                       └───────────────────────┘ │
└─────────────────────────────────────────────────┘
```

### Usage Pattern

**Cloudflare Worker (imports shared):**
```typescript
import {
  processAnalytics,
  generateRequestId,
  isValidSymbol,
  DEFAULT_SYMBOL,
  type RequestContext,
} from '@crypto-benchmark/shared';
```

**Vercel Edge (self-contained):**
```typescript
// All types and functions are inlined in the file
// This is due to Vercel Edge bundling requirements

interface OHLCData { /* ... */ }
function calculateVWAP(klines: OHLCData[]): VWAPData { /* ... */ }
```

## Mock vs Real Data Mode

### Architecture Decision

```
┌─────────────────────────────────────────────────────────────┐
│                    DATA MODE SWITCH                          │
│                                                              │
│  ┌─────────────────────┐    ┌─────────────────────────────┐ │
│  │    MOCK MODE        │    │      REAL MODE              │ │
│  │    (default)        │    │      (optional)             │ │
│  │                     │    │                             │ │
│  │  ┌───────────────┐  │    │  ┌───────────────────────┐  │ │
│  │  │ generateMock  │  │    │  │   Binance API         │  │ │
│  │  │ Ticker()      │  │    │  │   /api/v3/ticker/24hr │  │ │
│  │  └───────────────┘  │    │  └───────────────────────┘  │ │
│  │  ┌───────────────┐  │    │  ┌───────────────────────┐  │ │
│  │  │ generateMock  │  │    │  │   Binance API         │  │ │
│  │  │ OHLC()        │  │    │  │   /api/v3/klines      │  │ │
│  │  └───────────────┘  │    │  └───────────────────────┘  │ │
│  │                     │    │                             │ │
│  │  Benefits:          │    │  Benefits:                  │ │
│  │  - No external deps │    │  - Real market data         │ │
│  │  - Consistent data  │    │  - Production testing       │ │
│  │  - No rate limits   │    │                             │ │
│  │  - No geo-blocks    │    │  Drawbacks:                 │ │
│  │                     │    │  - Geo-restrictions         │ │
│  │                     │    │  - Rate limits              │ │
│  │                     │    │  - External latency variance│ │
│  └─────────────────────┘    └─────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
```

### Toggle Mock Mode

```typescript
import { setMockMode, isMockMode } from '@crypto-benchmark/shared';

// Check current mode
console.log(isMockMode());  // true (default)

// Switch to real API
setMockMode(false);

// Switch back to mock
setMockMode(true);
```

## Benchmark Architecture

### k6 Test Harness

```
┌─────────────────────────────────────────────────────────────┐
│                      k6 TEST RUNNER                          │
│                                                              │
│  ┌──────────────────────────────────────────────────────┐   │
│  │                    SCENARIOS                          │   │
│  │                                                       │   │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐   │   │
│  │  │ cold-start  │  │ warm-perf   │  │ load-test   │   │   │
│  │  │ 1 VU        │  │ 1 VU        │  │ 10 VUs      │   │   │
│  │  │ 10 iters    │  │ 1000 iters  │  │ 30 seconds  │   │   │
│  │  └─────────────┘  └─────────────┘  └─────────────┘   │   │
│  │                                                       │   │
│  │  ┌─────────────┐                                      │   │
│  │  │ burst-test  │                                      │   │
│  │  │ 0→100 VUs   │                                      │   │
│  │  │ 60 seconds  │                                      │   │
│  │  └─────────────┘                                      │   │
│  └──────────────────────────────────────────────────────┘   │
│                           │                                  │
│                           ▼                                  │
│  ┌──────────────────────────────────────────────────────┐   │
│  │                   CUSTOM METRICS                      │   │
│  │                                                       │   │
│  │  • http_req_duration (built-in)                      │   │
│  │  • processing_time_ms (server-reported)              │   │
│  │  • fetch_time_ms (data fetch time)                   │   │
│  │  • compute_time_ms (VWAP calculation)                │   │
│  │  • error_rate (failed requests)                      │   │
│  └──────────────────────────────────────────────────────┘   │
│                           │                                  │
│                           ▼                                  │
│  ┌──────────────────────────────────────────────────────┐   │
│  │                   OUTPUT                              │   │
│  │                                                       │   │
│  │  benchmark/results/warm-performance-cloudflare-*.json │   │
│  │  benchmark/results/load-test-vercel-*.json           │   │
│  └──────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

### Analysis Pipeline

```
benchmark/results/*.json
         │
         ▼
┌─────────────────────────────────────┐
│        analyze.py                    │
│                                      │
│  • Load all JSON results            │
│  • Statistical comparison           │
│  • t-tests for significance         │
│  • Generate summary tables          │
└─────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────┐
│        visualize.py                  │
│                                      │
│  • Latency distribution charts      │
│  • Throughput comparison bars       │
│  • P50/P95/P99 percentile plots     │
│  • Error rate graphs                │
└─────────────────────────────────────┘
         │
         ▼
   benchmark/analysis/output/
```

## Security Considerations

| Concern | Mitigation |
|---------|------------|
| API Keys | No secrets in code; mock mode default |
| CORS | Permissive for benchmarking (`*`) |
| Rate Limiting | Edge platform limits apply |
| Input Validation | Symbol/interval validation before processing |
| Error Exposure | Generic error messages, no stack traces |

## Scalability

| Factor | Cloudflare | Vercel |
|--------|------------|--------|
| Auto-scaling | Automatic | Automatic |
| Geographic distribution | 300+ PoPs | Global edge network |
| Concurrency | Isolate-per-request | Function-per-request |
| Cold start overhead | ~0-5ms | ~5-15ms |
| Request limits | 100K/day (free) | 100K/day (hobby) |
