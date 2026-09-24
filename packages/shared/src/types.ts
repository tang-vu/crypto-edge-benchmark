/**
 * Shared Types for Crypto Edge Benchmark
 * 
 * These types ensure consistency across all deployment strategies
 * for fair performance comparison.
 */

// ============================================
// Price Data Types
// ============================================

export interface PriceData {
  symbol: string;
  price: number;
  timestamp: number;
  volume?: number;
  quoteVolume?: number;
}

export interface OHLCData {
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  timestamp: number;
  closeTime: number;
}

export interface VWAPData {
  vwap: number;
  cumulativeVolume: number;
  cumulativeTPV: number; // Total Price * Volume
}

// ============================================
// API Response Types
// ============================================

export interface CryptoAnalyticsResponse {
  success: boolean;
  data?: CryptoAnalyticsData;
  error?: string;
  metadata: ResponseMetadata;
}

export interface CryptoAnalyticsData {
  symbol: string;
  timestamp: number;
  currentPrice: number;
  ohlc: OHLCData;
  vwap: number;
  priceChange24h: number;
  priceChangePercent24h: number;
  volume24h: number;
}

export interface ResponseMetadata {
  platform: 'cloudflare-worker' | 'lambda-edge' | 'vercel-edge';
  region: string;
  processingTimeMs: number;
  fetchTimeMs: number;
  computeTimeMs: number;
  coldStart: boolean;
  requestId: string;
  timestamp: number;
  dataMode?: 'mock' | 'live';
}

// ============================================
// Binance API Types
// ============================================

export interface BinanceTickerResponse {
  symbol: string;
  priceChange: string;
  priceChangePercent: string;
  weightedAvgPrice: string;
  prevClosePrice: string;
  lastPrice: string;
  lastQty: string;
  bidPrice: string;
  bidQty: string;
  askPrice: string;
  askQty: string;
  openPrice: string;
  highPrice: string;
  lowPrice: string;
  volume: string;
  quoteVolume: string;
  openTime: number;
  closeTime: number;
  firstId: number;
  lastId: number;
  count: number;
}

export interface BinanceKlineResponse {
  openTime: number;
  open: string;
  high: string;
  low: string;
  close: string;
  volume: string;
  closeTime: number;
  quoteAssetVolume: string;
  numberOfTrades: number;
  takerBuyBaseAssetVolume: string;
  takerBuyQuoteAssetVolume: string;
}

// ============================================
// Benchmark Types
// ============================================

export interface BenchmarkConfig {
  endpoints: EndpointConfig[];
  scenarios: ScenarioConfig[];
  warmupRequests: number;
  testDurationSeconds: number;
  virtualUsers: number;
}

export interface EndpointConfig {
  name: string;
  url: string;
  platform: 'cloudflare-worker' | 'lambda-edge' | 'vercel-edge';
}

export interface ScenarioConfig {
  name: string;
  type: 'cold-start' | 'warm-performance' | 'load-test' | 'burst-test';
  duration: string;
  vus: number;
  rampUp?: string;
  rampDown?: string;
}

export interface BenchmarkResult {
  endpoint: string;
  platform: string;
  scenario: string;
  timestamp: number;
  metrics: BenchmarkMetrics;
}

export interface BenchmarkMetrics {
  latencyP50: number;
  latencyP90: number;
  latencyP95: number;
  latencyP99: number;
  latencyAvg: number;
  latencyMin: number;
  latencyMax: number;
  throughput: number;
  errorRate: number;
  requestCount: number;
  coldStartLatency?: number;
}

// ============================================
// Request Context Types
// ============================================

export interface RequestContext {
  requestId: string;
  startTime: number;
  coldStart: boolean;
  region: string;
  platform: 'cloudflare-worker' | 'lambda-edge' | 'vercel-edge';
  dataMode?: 'mock' | 'live';
}

// ============================================
// Query Parameters
// ============================================

export interface AnalyticsQueryParams {
  symbol?: string;
  interval?: '1m' | '5m' | '15m' | '1h' | '4h' | '1d';
}

// ============================================
// Constants
// ============================================

export const SUPPORTED_SYMBOLS = [
  'BTCUSDT',
  'ETHUSDT',
  'BNBUSDT',
  'SOLUSDT',
  'XRPUSDT',
  'ADAUSDT',
  'DOGEUSDT',
  'AVAXUSDT',
  'DOTUSDT',
  'MATICUSDT'
] as const;

export type SupportedSymbol = typeof SUPPORTED_SYMBOLS[number];

export const SUPPORTED_INTERVALS = ['1m', '5m', '15m', '1h', '4h', '1d'] as const;
export type SupportedInterval = typeof SUPPORTED_INTERVALS[number];

export const DEFAULT_SYMBOL: SupportedSymbol = 'BTCUSDT';
export const DEFAULT_INTERVAL: SupportedInterval = '1h';
