/**
 * Shared constants for JSL Client Portfolio Portal.
 */

export const CHART_COLORS = {
  portfolio: '#0d9488',
  benchmark: '#3b82f6',
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

export const SECTOR_COLORS = {
  'Banking': '#0d9488',
  'Financial Services': '#14b8a6',
  'IT': '#6366f1',
  'Pharma': '#ec4899',
  'Healthcare': '#f472b6',
  'FMCG': '#22c55e',
  'Automobiles': '#3b82f6',
  'Auto Ancillaries': '#60a5fa',
  'Capital Goods': '#8b5cf6',
  'Metals': '#f59e0b',
  'Oil & Gas': '#ef4444',
  'Power': '#f97316',
  'Infrastructure': '#a855f7',
  'Chemicals': '#06b6d4',
  'Telecom': '#84cc16',
  'Real Estate': '#d946ef',
  'Cement': '#78716c',
  'Consumer Durables': '#0ea5e9',
  'Consumer': '#0ea5e9',
  'Insurance': '#10b981',
  'Conglomerate': '#64748b',
  'Building Materials': '#a3a3a3',
  'Cash': '#d97706',
  'Diversified': '#94a3b8',
  'Other': '#94a3b8',
  'Paints': '#22d3ee',
  'Hospitality': '#fb923c',
  'Aviation': '#38bdf8',
  'Agri & Sugar': '#a3e635',
  'Media & Entertainment': '#c084fc',
  'Internet & E-Commerce': '#2dd4bf',
  'Housing Finance': '#67e8f9',
  'Textiles': '#fbbf24',
  'Logistics': '#818cf8',
  'Staffing': '#a78bfa',
};

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
