/**
 * Cloudflare Worker Entry Point
 * 
 * This worker serves as the edge endpoint for crypto analytics.
 * It uses V8 Isolates for near-zero cold start times.
 */

import {
  processAnalytics,
  generateRequestId,
  isValidSymbol,
  isValidInterval,
  setMockMode,
  DEFAULT_SYMBOL,
  DEFAULT_INTERVAL,
  type RequestContext,
  type SupportedSymbol,
  type SupportedInterval
} from '@crypto-benchmark/shared';

// Track cold start
let isWarm = false;

export interface Env {
  PLATFORM: string;
}

export default {
  async fetch(request: Request, env: Env, _ctx: ExecutionContext): Promise<Response> {
    const startTime = performance.now();
    const coldStart = !isWarm;
    isWarm = true;

    // Get request info
    const url = new URL(request.url);
    const path = url.pathname;

    // CORS headers for benchmark testing
    const corsHeaders = {
      'Access-Control-Allow-Origin': '*',
      'Access-Control-Allow-Methods': 'GET, OPTIONS',
      'Access-Control-Allow-Headers': 'Content-Type',
    };

    // Handle CORS preflight
    if (request.method === 'OPTIONS') {
      return new Response(null, { headers: corsHeaders });
    }

    // Route handling
    if (path === '/health' || path === '/') {
      return jsonResponse({
        status: 'healthy',
        platform: 'cloudflare-worker',
        timestamp: Date.now(),
        coldStart,
      }, corsHeaders);
    }

    if (path === '/api/crypto-analytics') {
      return handleCryptoAnalytics(request, env, coldStart, startTime, corsHeaders);
    }

    // 404 for unknown routes
    return jsonResponse({
      error: 'Not Found',
      availableEndpoints: ['/health', '/api/crypto-analytics']
    }, corsHeaders, 404);
  },
};

async function handleCryptoAnalytics(
  request: Request,
  _env: Env,
  coldStart: boolean,
  startTime: number,
  corsHeaders: Record<string, string>
): Promise<Response> {
  const url = new URL(request.url);
  
  // Parse query parameters
  const symbolParam = url.searchParams.get('symbol') || DEFAULT_SYMBOL;
  const intervalParam = url.searchParams.get('interval') || DEFAULT_INTERVAL;
  // Data mode toggle: default mock=true (preserves Jan 2026 baseline behavior).
  // ?mockData=false uses live Binance API. Module-level state in shared/price-fetcher
  // persists across requests in the same isolate — benchmark runs use one mode at a time.
  const useMock = url.searchParams.get('mockData') !== 'false';
  setMockMode(useMock);

  // Validate parameters
  if (!isValidSymbol(symbolParam)) {
    return jsonResponse({
      success: false,
      error: `Invalid symbol: ${symbolParam}. Supported: BTCUSDT, ETHUSDT, BNBUSDT, etc.`
    }, corsHeaders, 400);
  }

  if (!isValidInterval(intervalParam)) {
    return jsonResponse({
      success: false,
      error: `Invalid interval: ${intervalParam}. Supported: 1m, 5m, 15m, 1h, 4h, 1d`
    }, corsHeaders, 400);
  }

  // Create request context (dataMode tagged for downstream analysis)
  const context: RequestContext = {
    requestId: generateRequestId(),
    startTime,
    coldStart,
    region: (request.cf as { colo?: string })?.colo || 'unknown',
    platform: 'cloudflare-worker',
    dataMode: useMock ? 'mock' : 'live',
  };

  // Process analytics
  const result = await processAnalytics(
    symbolParam as SupportedSymbol,
    intervalParam as SupportedInterval,
    context
  );

  // Return response
  const status = result.success ? 200 : 500;
  return jsonResponse(result, corsHeaders, status);
}

function jsonResponse(
  data: unknown,
  extraHeaders: Record<string, string> = {},
  status: number = 200
): Response {
  return new Response(JSON.stringify(data, null, 2), {
    status,
    headers: {
      'Content-Type': 'application/json',
      'Cache-Control': 'no-store',
      ...extraHeaders,
    },
  });
}
