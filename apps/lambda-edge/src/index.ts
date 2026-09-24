/**
 * AWS Lambda Handler
 * 
 * Standard Lambda function for crypto analytics.
 * Used as a baseline comparison against Lambda@Edge.
 */

import type {
  APIGatewayProxyEvent,
  APIGatewayProxyResult,
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

const corsHeaders = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Methods': 'GET, OPTIONS',
  'Access-Control-Allow-Headers': 'Content-Type',
  'Content-Type': 'application/json',
};

export async function handler(
  event: APIGatewayProxyEvent,
  context: Context
): Promise<APIGatewayProxyResult> {
  const startTime = Date.now();
  const coldStart = !isWarm;
  isWarm = true;

  const path = event.path;

  // Handle health check
  if (path === '/health' || path === '/') {
    return {
      statusCode: 200,
      headers: corsHeaders,
      body: JSON.stringify({
        status: 'healthy',
        platform: 'lambda-edge',
        region: process.env.AWS_REGION || 'unknown',
        timestamp: Date.now(),
        coldStart,
        remainingTimeMs: context.getRemainingTimeInMillis(),
      }),
    };
  }

  // Handle crypto analytics
  if (path === '/api/crypto-analytics') {
    return handleCryptoAnalytics(event, context, coldStart, startTime);
  }

  // 404 for unknown routes
  return {
    statusCode: 404,
    headers: corsHeaders,
    body: JSON.stringify({
      error: 'Not Found',
      availableEndpoints: ['/health', '/api/crypto-analytics'],
    }),
  };
}

async function handleCryptoAnalytics(
  event: APIGatewayProxyEvent,
  context: Context,
  coldStart: boolean,
  startTime: number
): Promise<APIGatewayProxyResult> {
  // Parse query parameters
  const params = event.queryStringParameters || {};
  const symbolParam = params.symbol || DEFAULT_SYMBOL;
  const intervalParam = params.interval || DEFAULT_INTERVAL;

  // Validate parameters
  if (!isValidSymbol(symbolParam)) {
    return {
      statusCode: 400,
      headers: corsHeaders,
      body: JSON.stringify({
        success: false,
        error: `Invalid symbol: ${symbolParam}. Supported: BTCUSDT, ETHUSDT, BNBUSDT, etc.`,
      }),
    };
  }

  if (!isValidInterval(intervalParam)) {
    return {
      statusCode: 400,
      headers: corsHeaders,
      body: JSON.stringify({
        success: false,
        error: `Invalid interval: ${intervalParam}. Supported: 1m, 5m, 15m, 1h, 4h, 1d`,
      }),
    };
  }

  // Create request context
  const requestContext: RequestContext = {
    requestId: context.awsRequestId || generateRequestId(),
    startTime,
    coldStart,
    region: process.env.AWS_REGION || 'unknown',
    platform: 'lambda-edge',
  };

  // Process analytics
  const result = await processAnalytics(
    symbolParam as SupportedSymbol,
    intervalParam as SupportedInterval,
    requestContext
  );

  return {
    statusCode: result.success ? 200 : 500,
    headers: corsHeaders,
    body: JSON.stringify(result, null, 2),
  };
}
