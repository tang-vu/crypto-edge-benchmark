/**
 * Crypto Analytics Computations
 * 
 * Core analytics logic for processing crypto price data.
 * This module is shared across all deployment strategies to ensure
 * fair performance comparison.
 */

import type {
  OHLCData,
  VWAPData,
  CryptoAnalyticsData,
  CryptoAnalyticsResponse,
  ResponseMetadata,
  RequestContext,
  SupportedSymbol,
  SupportedInterval,
  BinanceTickerResponse
} from './types.js';

import {
  fetch24hrTicker,
  fetchOHLC,
  fetchKlinesForVWAP
} from './price-fetcher.js';

/**
 * Calculate VWAP (Volume Weighted Average Price)
 * 
 * VWAP = Σ(Typical Price × Volume) / Σ(Volume)
 * Typical Price = (High + Low + Close) / 3
 */
export function calculateVWAP(klines: OHLCData[]): VWAPData {
  let cumulativeTPV = 0; // Cumulative (Typical Price × Volume)
  let cumulativeVolume = 0;

  for (const kline of klines) {
    const typicalPrice = (kline.high + kline.low + kline.close) / 3;
    cumulativeTPV += typicalPrice * kline.volume;
    cumulativeVolume += kline.volume;
  }

  const vwap = cumulativeVolume > 0 ? cumulativeTPV / cumulativeVolume : 0;

  return {
    vwap,
    cumulativeVolume,
    cumulativeTPV,
  };
}

/**
 * Calculate Simple Moving Average
 */
export function calculateSMA(prices: number[], period: number): number {
  if (prices.length < period) {
    return prices.reduce((a, b) => a + b, 0) / prices.length;
  }
  
  const slice = prices.slice(-period);
  return slice.reduce((a, b) => a + b, 0) / period;
}

/**
 * Calculate Exponential Moving Average
 */
export function calculateEMA(prices: number[], period: number): number {
  if (prices.length === 0) return 0;
  if (prices.length === 1) return prices[0];

  const multiplier = 2 / (period + 1);
  let ema = prices[0];

  for (let i = 1; i < prices.length; i++) {
    ema = (prices[i] - ema) * multiplier + ema;
  }

  return ema;
}

/**
 * Parse Binance ticker response to extract analytics data
 */
function parseTickerData(ticker: BinanceTickerResponse, ohlc: OHLCData, vwap: number): CryptoAnalyticsData {
  return {
    symbol: ticker.symbol,
    timestamp: Date.now(),
    currentPrice: parseFloat(ticker.lastPrice),
    ohlc: ohlc,
    vwap: vwap,
    priceChange24h: parseFloat(ticker.priceChange),
    priceChangePercent24h: parseFloat(ticker.priceChangePercent),
    volume24h: parseFloat(ticker.volume),
  };
}

/**
 * Main analytics processing function
 * 
 * This is the core workload that will be benchmarked.
 * It fetches data and performs computations.
 */
export async function processAnalytics(
  symbol: SupportedSymbol,
  interval: SupportedInterval,
  context: RequestContext
): Promise<CryptoAnalyticsResponse> {
  const fetchStart = performance.now();
  
  try {
    // Parallel fetch for better performance
    const [ticker, ohlcData, vwapKlines] = await Promise.all([
      fetch24hrTicker(symbol),
      fetchOHLC(symbol, interval, 1),
      fetchKlinesForVWAP(symbol, interval, 24),
    ]);

    const fetchEnd = performance.now();
    const fetchTimeMs = fetchEnd - fetchStart;

    // Compute VWAP
    const computeStart = performance.now();
    const vwapData = calculateVWAP(vwapKlines);
    const computeEnd = performance.now();
    const computeTimeMs = computeEnd - computeStart;

    // Build response
    const currentOHLC = ohlcData[0];
    const analyticsData = parseTickerData(ticker, currentOHLC, vwapData.vwap);

    const totalProcessingTime = performance.now() - context.startTime;

    const metadata: ResponseMetadata = {
      platform: context.platform,
      region: context.region,
      processingTimeMs: totalProcessingTime,
      fetchTimeMs: fetchTimeMs,
      computeTimeMs: computeTimeMs,
      coldStart: context.coldStart,
      requestId: context.requestId,
      timestamp: Date.now(),
      dataMode: context.dataMode,
    };

    return {
      success: true,
      data: analyticsData,
      metadata,
    };

  } catch (error) {
    const totalProcessingTime = performance.now() - context.startTime;

    const metadata: ResponseMetadata = {
      platform: context.platform,
      region: context.region,
      processingTimeMs: totalProcessingTime,
      fetchTimeMs: 0,
      computeTimeMs: 0,
      coldStart: context.coldStart,
      requestId: context.requestId,
      timestamp: Date.now(),
      dataMode: context.dataMode,
    };

    return {
      success: false,
      error: error instanceof Error ? error.message : 'Unknown error',
      metadata,
    };
  }
}

/**
 * Generate a unique request ID
 */
export function generateRequestId(): string {
  return `req_${Date.now()}_${Math.random().toString(36).substring(2, 9)}`;
}

/**
 * Validate symbol parameter
 */
export function isValidSymbol(symbol: string): symbol is SupportedSymbol {
  const validSymbols = [
    'BTCUSDT', 'ETHUSDT', 'BNBUSDT', 'SOLUSDT', 'XRPUSDT',
    'ADAUSDT', 'DOGEUSDT', 'AVAXUSDT', 'DOTUSDT', 'MATICUSDT'
  ];
  return validSymbols.includes(symbol);
}

/**
 * Validate interval parameter
 */
export function isValidInterval(interval: string): interval is SupportedInterval {
  const validIntervals = ['1m', '5m', '15m', '1h', '4h', '1d'];
  return validIntervals.includes(interval);
}
