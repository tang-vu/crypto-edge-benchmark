/**
 * Shared Package Entry Point
 * 
 * Exports all shared functionality for edge deployment strategies.
 */

// Types
export * from './types.js';

// Price Fetcher
export {
  fetchCurrentPrice,
  fetch24hrTicker,
  fetchOHLC,
  fetchKlinesForVWAP,
  fetchMultiplePrices,
  checkBinanceHealth,
  setMockMode,
  isMockMode,
} from './price-fetcher.js';

// Crypto Analytics
export {
  calculateVWAP,
  calculateSMA,
  calculateEMA,
  processAnalytics,
  generateRequestId,
  isValidSymbol,
  isValidInterval,
} from './crypto-analytics.js';
