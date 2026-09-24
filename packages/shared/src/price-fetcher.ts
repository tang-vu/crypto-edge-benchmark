/**
 * Price Fetcher with Mock Data Support
 * 
 * Supports both real Binance API and mock data for benchmarking.
 * Mock mode generates realistic synthetic data to avoid external API 
 * latency variance and geo-restrictions.
 */

import type {
  PriceData,
  BinanceTickerResponse,
  OHLCData,
  SupportedSymbol,
  SupportedInterval
} from './types.js';

const BINANCE_API_BASE = 'https://api.binance.com/api/v3';

// Configuration for mock data mode
let useMockData = true; // Default to mock for benchmarking

export function setMockMode(enabled: boolean): void {
  useMockData = enabled;
}

export function isMockMode(): boolean {
  return useMockData;
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
  const volatility = 0.02; // 2% daily volatility
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
    const volatility = 0.005; // 0.5% per candle
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

/**
 * Fetch current price for a symbol
 */
export async function fetchCurrentPrice(symbol: SupportedSymbol): Promise<PriceData> {
  if (useMockData) {
    const ticker = generateMockTicker(symbol);
    return {
      symbol: ticker.symbol,
      price: parseFloat(ticker.lastPrice),
      timestamp: Date.now(),
      volume: parseFloat(ticker.volume),
      quoteVolume: parseFloat(ticker.quoteVolume),
    };
  }

  const url = `${BINANCE_API_BASE}/ticker/24hr?symbol=${symbol}`;
  
  const response = await fetch(url, {
    headers: {
      'Accept': 'application/json',
    },
  });

  if (!response.ok) {
    throw new Error(`Binance API error: ${response.status} ${response.statusText}`);
  }

  const data = await response.json() as BinanceTickerResponse;

  return {
    symbol: data.symbol,
    price: parseFloat(data.lastPrice),
    timestamp: Date.now(),
    volume: parseFloat(data.volume),
    quoteVolume: parseFloat(data.quoteVolume),
  };
}

/**
 * Fetch 24hr ticker data with price change information
 */
export async function fetch24hrTicker(symbol: SupportedSymbol): Promise<BinanceTickerResponse> {
  if (useMockData) {
    return generateMockTicker(symbol);
  }

  const url = `${BINANCE_API_BASE}/ticker/24hr?symbol=${symbol}`;
  
  const response = await fetch(url, {
    headers: {
      'Accept': 'application/json',
    },
  });

  if (!response.ok) {
    throw new Error(`Binance API error: ${response.status} ${response.statusText}`);
  }

  return await response.json() as BinanceTickerResponse;
}

/**
 * Fetch OHLC (Kline/Candlestick) data
 */
export async function fetchOHLC(
  symbol: SupportedSymbol,
  interval: SupportedInterval = '1h',
  limit: number = 1
): Promise<OHLCData[]> {
  if (useMockData) {
    return generateMockOHLC(symbol, interval, limit);
  }

  const url = `${BINANCE_API_BASE}/klines?symbol=${symbol}&interval=${interval}&limit=${limit}`;
  
  const response = await fetch(url, {
    headers: {
      'Accept': 'application/json',
    },
  });

  if (!response.ok) {
    throw new Error(`Binance API error: ${response.status} ${response.statusText}`);
  }

  // Binance returns array of arrays
  const rawData = await response.json() as unknown[][];

  return rawData.map((kline): OHLCData => ({
    timestamp: kline[0] as number,
    open: parseFloat(kline[1] as string),
    high: parseFloat(kline[2] as string),
    low: parseFloat(kline[3] as string),
    close: parseFloat(kline[4] as string),
    volume: parseFloat(kline[5] as string),
    closeTime: kline[6] as number,
  }));
}

/**
 * Fetch multiple klines for VWAP calculation
 */
export async function fetchKlinesForVWAP(
  symbol: SupportedSymbol,
  interval: SupportedInterval = '1h',
  limit: number = 24
): Promise<OHLCData[]> {
  return fetchOHLC(symbol, interval, limit);
}

/**
 * Batch fetch prices for multiple symbols
 */
export async function fetchMultiplePrices(symbols: SupportedSymbol[]): Promise<Map<string, PriceData>> {
  const promises = symbols.map(symbol => fetchCurrentPrice(symbol));
  const results = await Promise.all(promises);
  
  const priceMap = new Map<string, PriceData>();
  results.forEach(price => {
    priceMap.set(price.symbol, price);
  });
  
  return priceMap;
}

/**
 * Health check for Binance API
 */
export async function checkBinanceHealth(): Promise<boolean> {
  try {
    const response = await fetch(`${BINANCE_API_BASE}/ping`);
    return response.ok;
  } catch {
    return false;
  }
}
