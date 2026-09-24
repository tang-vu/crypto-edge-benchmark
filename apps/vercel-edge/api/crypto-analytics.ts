/**
 * Vercel Edge Function - Crypto Analytics
 * 
 * Self-contained implementation for Vercel Edge deployment.
 * Includes all necessary types and logic for the benchmark.
 */

export const config = {
  runtime: 'edge',
};

// ============================================
// Types
// ============================================

interface OHLCData {
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  timestamp: number;
  closeTime: number;
}

interface VWAPData {
  vwap: number;
  cumulativeVolume: number;
  cumulativeTPV: number;
}

interface BinanceTickerResponse {
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

interface CryptoAnalyticsData {
  symbol: string;
  timestamp: number;
  currentPrice: number;
  ohlc: OHLCData;
  vwap: number;
  priceChange24h: number;
  priceChangePercent24h: number;
  volume24h: number;
}

interface ResponseMetadata {
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

interface CryptoAnalyticsResponse {
  success: boolean;
  data?: CryptoAnalyticsData;
  error?: string;
  metadata: ResponseMetadata;
}

interface RequestContext {
  requestId: string;
  startTime: number;
  coldStart: boolean;
  region: string;
  platform: 'cloudflare-worker' | 'lambda-edge' | 'vercel-edge';
  dataMode?: 'mock' | 'live';
}

type SupportedSymbol = 'BTCUSDT' | 'ETHUSDT' | 'BNBUSDT' | 'SOLUSDT' | 'XRPUSDT' | 
  'ADAUSDT' | 'DOGEUSDT' | 'AVAXUSDT' | 'DOTUSDT' | 'MATICUSDT';

type SupportedInterval = '1m' | '5m' | '15m' | '1h' | '4h' | '1d';

const DEFAULT_SYMBOL: SupportedSymbol = 'BTCUSDT';
const DEFAULT_INTERVAL: SupportedInterval = '1h';

// ============================================
// Live Binance API fetchers (real-API mode, R1.1)
// ============================================

const BINANCE_API_BASE = 'https://api.binance.com/api/v3';

async function fetchBinanceTicker(symbol: SupportedSymbol): Promise<BinanceTickerResponse> {
  const res = await fetch(`${BINANCE_API_BASE}/ticker/24hr?symbol=${symbol}`, {
    headers: { Accept: 'application/json' },
  });
  if (!res.ok) {
    throw new Error(`Binance ticker error: ${res.status} ${res.statusText}`);
  }
  return (await res.json()) as BinanceTickerResponse;
}

async function fetchBinanceKlines(
  symbol: SupportedSymbol,
  interval: SupportedInterval,
  limit: number
): Promise<OHLCData[]> {
  const res = await fetch(
    `${BINANCE_API_BASE}/klines?symbol=${symbol}&interval=${interval}&limit=${limit}`,
    { headers: { Accept: 'application/json' } }
  );
  if (!res.ok) {
    throw new Error(`Binance klines error: ${res.status} ${res.statusText}`);
  }
  // Binance returns array-of-arrays: [openTime, open, high, low, close, volume, closeTime, ...]
  const raw = (await res.json()) as unknown[][];
  return raw.map((k) => ({
    timestamp: Number(k[0]),
    open: parseFloat(String(k[1])),
    high: parseFloat(String(k[2])),
    low: parseFloat(String(k[3])),
    close: parseFloat(String(k[4])),
    volume: parseFloat(String(k[5])),
    closeTime: Number(k[6]),
  }));
}

// ============================================
// Mock Data Generators
// ============================================

const MOCK_PRICES: Record<string, number> = {
  BTCUSDT: 97500.00,
  ETHUSDT: 3450.00,
  BNBUSDT: 685.00,
  SOLUSDT: 195.00,
  XRPUSDT: 2.35,
  ADAUSDT: 0.95,
  DOGEUSDT: 0.38,
  AVAXUSDT: 42.50,
  DOTUSDT: 7.80,
  MATICUSDT: 0.52,
};

function generateMockTicker(symbol: SupportedSymbol): BinanceTickerResponse {
  const basePrice = MOCK_PRICES[symbol] || 100;
  const volatility = 0.02;
  const priceChange = basePrice * volatility * (Math.random() - 0.5) * 2;
  const volume = basePrice > 1000 ? 50000 + Math.random() * 10000 : 5000000 + Math.random() * 1000000;
  
  return {
    symbol,
    priceChange: priceChange.toFixed(8),
    priceChangePercent: ((priceChange / basePrice) * 100).toFixed(2),
    weightedAvgPrice: basePrice.toFixed(8),
    prevClosePrice: (basePrice - priceChange).toFixed(8),
    lastPrice: basePrice.toFixed(8),
    lastQty: (Math.random() * 10).toFixed(8),
    bidPrice: (basePrice - 0.01).toFixed(8),
    bidQty: (Math.random() * 100).toFixed(8),
    askPrice: (basePrice + 0.01).toFixed(8),
    askQty: (Math.random() * 100).toFixed(8),
    openPrice: (basePrice - priceChange).toFixed(8),
    highPrice: (basePrice * 1.01).toFixed(8),
    lowPrice: (basePrice * 0.99).toFixed(8),
    volume: volume.toFixed(8),
    quoteVolume: (volume * basePrice).toFixed(8),
    openTime: Date.now() - 86400000,
    closeTime: Date.now(),
    firstId: 1000000,
    lastId: 1100000,
    count: 100000,
  };
}

function generateMockOHLC(
  symbol: SupportedSymbol,
  interval: SupportedInterval,
  limit: number
): OHLCData[] {
  const basePrice = MOCK_PRICES[symbol] || 100;
  const klines: OHLCData[] = [];
  
  const intervalMs: Record<SupportedInterval, number> = {
    '1m': 60000,
    '5m': 300000,
    '15m': 900000,
    '1h': 3600000,
    '4h': 14400000,
    '1d': 86400000,
  };
  
  const ms = intervalMs[interval];
  const now = Date.now();
  
  for (let i = limit - 1; i >= 0; i--) {
    const timestamp = now - (i * ms);
    const volatility = 0.005;
    const randomFactor = (Math.random() - 0.5) * 2 * volatility;
    
    const open = basePrice * (1 + randomFactor);
    const close = open * (1 + (Math.random() - 0.5) * volatility);
    const high = Math.max(open, close) * (1 + Math.random() * volatility * 0.5);
    const low = Math.min(open, close) * (1 - Math.random() * volatility * 0.5);
    const volume = basePrice > 1000 ? 1000 + Math.random() * 500 : 100000 + Math.random() * 50000;
    
    klines.push({
      timestamp,
      open,
      high,
      low,
      close,
      volume,
      closeTime: timestamp + ms - 1,
    });
  }
  
  return klines;
}

// ============================================
// Analytics Functions
// ============================================

function calculateVWAP(klines: OHLCData[]): VWAPData {
  let cumulativeTPV = 0;
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

function generateRequestId(): string {
  return `req_${Date.now()}_${Math.random().toString(36).substring(2, 9)}`;
}

function isValidSymbol(symbol: string): symbol is SupportedSymbol {
  const validSymbols = [
    'BTCUSDT', 'ETHUSDT', 'BNBUSDT', 'SOLUSDT', 'XRPUSDT',
    'ADAUSDT', 'DOGEUSDT', 'AVAXUSDT', 'DOTUSDT', 'MATICUSDT'
  ];
  return validSymbols.includes(symbol);
}

function isValidInterval(interval: string): interval is SupportedInterval {
  const validIntervals = ['1m', '5m', '15m', '1h', '4h', '1d'];
  return validIntervals.includes(interval);
}

async function processAnalytics(
  symbol: SupportedSymbol,
  interval: SupportedInterval,
  context: RequestContext
): Promise<CryptoAnalyticsResponse> {
  const fetchStart = performance.now();
  
  try {
    // Branch on dataMode: live calls Binance in parallel; mock generates inline.
    const useMock = context.dataMode !== 'live';
    let ticker: BinanceTickerResponse;
    let ohlcData: OHLCData[];
    let vwapKlines: OHLCData[];
    if (useMock) {
      ticker = generateMockTicker(symbol);
      ohlcData = generateMockOHLC(symbol, interval, 1);
      vwapKlines = generateMockOHLC(symbol, interval, 24);
    } else {
      [ticker, ohlcData, vwapKlines] = await Promise.all([
        fetchBinanceTicker(symbol),
        fetchBinanceKlines(symbol, interval, 1),
        fetchBinanceKlines(symbol, interval, 24),
      ]);
    }

    const fetchEnd = performance.now();
    const fetchTimeMs = fetchEnd - fetchStart;

    // Compute VWAP
    const computeStart = performance.now();
    const vwapData = calculateVWAP(vwapKlines);
    const computeEnd = performance.now();
    const computeTimeMs = computeEnd - computeStart;

    // Build response
    const currentOHLC = ohlcData[0];
    const analyticsData: CryptoAnalyticsData = {
      symbol: ticker.symbol,
      timestamp: Date.now(),
      currentPrice: parseFloat(ticker.lastPrice),
      ohlc: currentOHLC,
      vwap: vwapData.vwap,
      priceChange24h: parseFloat(ticker.priceChange),
      priceChangePercent24h: parseFloat(ticker.priceChangePercent),
      volume24h: parseFloat(ticker.volume),
    };

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

// ============================================
// Handler
// ============================================

// Track cold start at module level
let isWarm = false;

export default async function handler(request: Request): Promise<Response> {
  const startTime = performance.now();
  const coldStart = !isWarm;
  isWarm = true;

  // Handle CORS preflight
  if (request.method === 'OPTIONS') {
    return new Response(null, {
      status: 204,
      headers: {
        'Access-Control-Allow-Origin': '*',
        'Access-Control-Allow-Methods': 'GET, OPTIONS',
        'Access-Control-Allow-Headers': 'Content-Type',
      },
    });
  }

  // Parse query parameters
  const url = new URL(request.url);
  const symbolParam = url.searchParams.get('symbol') || DEFAULT_SYMBOL;
  const intervalParam = url.searchParams.get('interval') || DEFAULT_INTERVAL;
  // Data mode toggle: ?mockData=false → live Binance API. Default mock (preserves baseline).
  const useMock = url.searchParams.get('mockData') !== 'false';

  // Validate parameters
  if (!isValidSymbol(symbolParam)) {
    return new Response(
      JSON.stringify({
        success: false,
        error: `Invalid symbol: ${symbolParam}. Supported: BTCUSDT, ETHUSDT, BNBUSDT, etc.`,
      }),
      {
        status: 400,
        headers: {
          'Content-Type': 'application/json',
          'Access-Control-Allow-Origin': '*',
        },
      }
    );
  }

  if (!isValidInterval(intervalParam)) {
    return new Response(
      JSON.stringify({
        success: false,
        error: `Invalid interval: ${intervalParam}. Supported: 1m, 5m, 15m, 1h, 4h, 1d`,
      }),
      {
        status: 400,
        headers: {
          'Content-Type': 'application/json',
          'Access-Control-Allow-Origin': '*',
        },
      }
    );
  }

  // Get region from Vercel headers
  const region = request.headers.get('x-vercel-id')?.split('::')[0] || 'unknown';

  // Create request context (dataMode propagates to response metadata for analysis tagging)
  const requestContext: RequestContext = {
    requestId: generateRequestId(),
    startTime,
    coldStart,
    region,
    platform: 'vercel-edge',
    dataMode: useMock ? 'mock' : 'live',
  };

  // Process analytics
  const result = await processAnalytics(
    symbolParam as SupportedSymbol,
    intervalParam as SupportedInterval,
    requestContext
  );

  return new Response(JSON.stringify(result, null, 2), {
    status: result.success ? 200 : 500,
    headers: {
      'Content-Type': 'application/json',
      'Access-Control-Allow-Origin': '*',
    },
  });
}
