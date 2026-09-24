/**
 * Vercel Edge Function - Health Check
 * 
 * Returns health status and platform information.
 */

export const config = {
  runtime: 'edge',
};

// Track cold start at module level
let isWarm = false;

export default async function handler(request: Request): Promise<Response> {
  const coldStart = !isWarm;
  isWarm = true;

  // Get region from Vercel headers
  const region = request.headers.get('x-vercel-id')?.split('::')[0] || 'unknown';

  const response = {
    status: 'healthy',
    platform: 'vercel-edge',
    region,
    timestamp: Date.now(),
    coldStart,
  };

  return new Response(JSON.stringify(response, null, 2), {
    status: 200,
    headers: {
      'Content-Type': 'application/json',
      'Access-Control-Allow-Origin': '*',
    },
  });
}
