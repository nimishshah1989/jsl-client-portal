/**
 * Shared constants for JSL Client Portfolio Portal.
 */

export const CHART_COLORS = {
  portfolio: '#0d9488',
  benchmark: '#94a3b8',
  cash: '#d97706',
  positive: '#059669',
  negative: '#dc2626',
  grid: '#f1f5f9',
  portfolioFill: 'rgba(13, 148, 136, 0.10)',
  negativeFill: 'rgba(220, 38, 38, 0.25)',
  cashFill: 'rgba(217, 119, 6, 0.40)',
};

export const TIME_RANGES = ['1M', '3M', '6M', '1Y', '2Y', '3Y', '5Y', 'ALL'];

export const ASSET_CLASS_COLORS = {
  Equity: '#0d9488',
  Cash: '#d97706',
  Debt: '#3b82f6',
  Gold: '#eab308',
  Others: '#8b5cf6',
  // Uppercase variants (API returns uppercase asset class names)
  EQUITY: '#0d9488',
  CASH: '#d97706',
  DEBT: '#3b82f6',
  GOLD: '#eab308',
  OTHERS: '#8b5cf6',
};

export const SECTOR_COLORS = [
  '#0d9488', '#3b82f6', '#8b5cf6', '#ec4899',
  '#f59e0b', '#ef4444', '#06b6d4', '#84cc16',
  '#94a3b8',
];

export const TXN_TYPE_STYLES = {
  BUY: { bg: 'bg-emerald-100', text: 'text-emerald-700' },
  SELL: { bg: 'bg-red-100', text: 'text-red-700' },
  BONUS: { bg: 'bg-blue-100', text: 'text-blue-700' },
  CORPUS_IN: { bg: 'bg-purple-100', text: 'text-purple-700' },
  SIP: { bg: 'bg-teal-100', text: 'text-teal-700' },
  DIVIDEND: { bg: 'bg-amber-100', text: 'text-amber-700' },
  SWITCH_IN: { bg: 'bg-indigo-100', text: 'text-indigo-700' },
  SWITCH_OUT: { bg: 'bg-orange-100', text: 'text-orange-700' },
  REDEMPTION: { bg: 'bg-red-100', text: 'text-red-700' },
};
