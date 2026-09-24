/**
 * Vercel Edge Function — No-Op Handler
 *
 * Minimal handler for framework overhead measurement (P9.5).
 * Does the literal minimum: parse query params, return JSON.
 * No analytics, no mock generation, no external package calls.
 *
 * The delta between full-handler (crypto-analytics.ts) latency and this
 * no-op latency isolates application-layer overhead: mock generation +
 * VWAP compute + JSON serialise + Next.js route-dispatch + CORS middleware.
 *
 * Deployed automatically as /api/noop alongside the existing project.
 * Benchmark endpoint: https://vercel-edge-murex.vercel.app/api/noop
 */

export const config = {
  runtime: 'edge',
};

// Module-level warm tracking mirrors main handler pattern
let isWarm = false;

export default async function handler(request: Request): Promise<Response> {
  const startTime = performance.now();
  const coldStart = !isWarm;
  isWarm = true;

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

  const url = new URL(request.url);

  // Parse query params to replicate framework dispatch cost without computation
  const symbol   = url.searchParams.get('symbol')   || 'BTCUSDT';
  const interval = url.searchParams.get('interval') || '1h';

  // Extract Vercel routing header — same read as full handler, for parity
  const xVercelId = request.headers.get('x-vercel-id') || null;
  const region    = xVercelId?.split('::')[0] || 'unknown';

  const processingTimeMs = performance.now() - startTime;

  return new Response(
    JSON.stringify({
      ok: true,
      symbol,
      interval,
      platform:        'vercel-noop',
      region,
      coldStart,
      processingTimeMs,
    }),
    {
      status: 200,
      headers: {
        'Content-Type':                'application/json',
        'Cache-Control':               'no-store',
        'Access-Control-Allow-Origin': '*',
      },
    }
  );
}
