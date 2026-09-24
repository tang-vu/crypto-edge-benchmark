/**
 * AWS Lambda@Edge Handler
 * 
 * Lambda@Edge function for crypto analytics.
 * Runs at CloudFront edge locations for lower latency.
 * 
 * Constraints:
 * - Max 5 seconds timeout (viewer request/response)
 * - Max 128MB memory
 * - Must be deployed to us-east-1
 * - No environment variables (use hardcoded values or fetch from external config)
 */

import type {
  CloudFrontRequestEvent,
  CloudFrontRequestResult,
  Context
} from 'aws-lambda';

import {
  processAnalytics,
  generateRequestId,
  isValidSymbol,
  isValidInterval,
  DEFAULT_SYMBOL,
  DEFAULT_INTERVAL,
  type RequestContext,
  type SupportedSymbol,
  type SupportedInterval
} from '@crypto-benchmark/shared';

// Track cold start
let isWarm = false;

export async function handler(
  event: CloudFrontRequestEvent,
  context: Context
): Promise<CloudFrontRequestResult> {
  const startTime = Date.now();
  const coldStart = !isWarm;
  isWarm = true;

  const request = event.Records[0].cf.request;
  const uri = request.uri;

  // Parse query string
  const queryString = request.querystring || '';
  const params = new URLSearchParams(queryString);

  // Handle health check
  if (uri === '/health' || uri === '/') {
    return createResponse(200, {
      status: 'healthy',
      platform: 'lambda-edge',
      region: event.Records[0].cf.config.distributionId,
      timestamp: Date.now(),
      coldStart,
    });
  }

  // Handle crypto analytics
  if (uri === '/api/crypto-analytics') {
    return handleCryptoAnalytics(params, context, coldStart, startTime, event);
  }

  // 404 for unknown routes
  return createResponse(404, {
    error: 'Not Found',
    availableEndpoints: ['/health', '/api/crypto-analytics'],
  });
}

async function handleCryptoAnalytics(
  params: URLSearchParams,
  context: Context,
  coldStart: boolean,
  startTime: number,
  event: CloudFrontRequestEvent
): Promise<CloudFrontRequestResult> {
  const symbolParam = params.get('symbol') || DEFAULT_SYMBOL;
  const intervalParam = params.get('interval') || DEFAULT_INTERVAL;

  // Validate parameters
  if (!isValidSymbol(symbolParam)) {
    return createResponse(400, {
      success: false,
      error: `Invalid symbol: ${symbolParam}. Supported: BTCUSDT, ETHUSDT, BNBUSDT, etc.`,
    });
  }

  if (!isValidInterval(intervalParam)) {
    return createResponse(400, {
      success: false,
      error: `Invalid interval: ${intervalParam}. Supported: 1m, 5m, 15m, 1h, 4h, 1d`,
    });
  }

  // Create request context
  const requestContext: RequestContext = {
    requestId: context.awsRequestId || generateRequestId(),
    startTime,
    coldStart,
    region: event.Records[0].cf.config.distributionDomainName || 'edge',
    platform: 'lambda-edge',
  };

  // Process analytics
  const result = await processAnalytics(
    symbolParam as SupportedSymbol,
    intervalParam as SupportedInterval,
    requestContext
  );

  return createResponse(result.success ? 200 : 500, result);
}

function createResponse(
  status: number,
  body: unknown
): CloudFrontRequestResult {
  return {
    status: status.toString(),
    statusDescription: status === 200 ? 'OK' : 'Error',
    headers: {
      'content-type': [{ key: 'Content-Type', value: 'application/json' }],
      'access-control-allow-origin': [{ key: 'Access-Control-Allow-Origin', value: '*' }],
      'cache-control': [{ key: 'Cache-Control', value: 'no-store' }],
    },
    body: JSON.stringify(body, null, 2),
  };
}
