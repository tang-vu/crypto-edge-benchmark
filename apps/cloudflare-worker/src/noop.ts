/**
 * Cloudflare Worker No-Op Handler
 *
 * Minimal handler for framework overhead measurement (P9.5).
 * Does the literal minimum: parse query params, return JSON.
 * No analytics, no mock generation, no shared-package call.
 *
 * The delta between full-handler latency and this no-op latency isolates
 * application-layer overhead (mock generation + VWAP compute + JSON serialise
 * + shared-package call) from pure network + CF-dispatch overhead.
 *
 * Deploy: deployed as a separate worker "crypto-analytics-noop" via wrangler.
 * Benchmark endpoint: https://crypto-analytics-noop.<account>.workers.dev/api/noop
 */

export interface Env {
  PLATFORM: string;
}

// Track warm state at module level — mirrors pattern in main worker
let isWarm = false;

export default {
  async fetch(request: Request, _env: Env, _ctx: ExecutionContext): Promise<Response> {
    const startTime = performance.now();
    const coldStart = !isWarm;
    isWarm = true;

    const url = new URL(request.url);

    // CORS preflight passthrough
    if (request.method === 'OPTIONS') {
      return new Response(null, {
        status: 204,
        headers: {
          'Access-Control-Allow-Origin':  '*',
          'Access-Control-Allow-Methods': 'GET, OPTIONS',
          'Access-Control-Allow-Headers': 'Content-Type',
        },
      });
    }

    // Health check
    if (url.pathname === '/health' || url.pathname === '/') {
      return _json({ status: 'healthy', platform: 'cloudflare-noop', coldStart });
    }

    // No-op endpoint — parse params only, return minimal JSON immediately
    if (url.pathname === '/api/noop') {
      // Parse query params to replicate framework dispatch cost without computation
      const symbol   = url.searchParams.get('symbol')   || 'BTCUSDT';
      const interval = url.searchParams.get('interval') || '1h';
      const processingTimeMs = performance.now() - startTime;

      return _json({
        ok: true,
        symbol,
        interval,
        platform:        'cloudflare-noop',
        coldStart,
        processingTimeMs,
      });
    }

    return _json({ error: 'Not Found', endpoints: ['/health', '/api/noop'] }, 404);
  },
};

function _json(data: unknown, status = 200): Response {
  return new Response(JSON.stringify(data), {
    status,
    headers: {
      'Content-Type':                'application/json',
      'Cache-Control':               'no-store',
      'Access-Control-Allow-Origin': '*',
    },
  });
}
