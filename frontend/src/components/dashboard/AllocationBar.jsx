'use client';

import { useAllocation } from '@/hooks/usePortfolio';
import { formatPctUnsigned } from '@/lib/format';
import Spinner from '@/components/ui/Spinner';

/**
 * Sector color palette — deterministic assignment by sector name.
 * Known sectors get fixed colors; unknown sectors get one from the pool.
 */
const SECTOR_COLORS = {
  'Banking': '#0d9488',
  'Financial Services': '#14b8a6',
  'IT': '#6366f1',
  'Pharma': '#ec4899',
  'Healthcare': '#f472b6',
  'FMCG': '#22c55e',
  'Automobiles': '#3b82f6',
  'Auto Ancillaries': '#60a5fa',
  'Capital Goods': '#8b5cf6',
  'Metals & Mining': '#f59e0b',
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
  'Gold': '#eab308',
  'Silver': '#9ca3af',
  'Diversified': '#94a3b8',
  'Other': '#94a3b8',
};

const FALLBACK_COLORS = [
  '#0d9488', '#6366f1', '#ec4899', '#f59e0b', '#3b82f6',
  '#22c55e', '#ef4444', '#8b5cf6', '#f97316', '#06b6d4',
];

function getSectorColor(name, index) {
  return SECTOR_COLORS[name] || FALLBACK_COLORS[index % FALLBACK_COLORS.length];
}

export default function AllocationBar() {
  const { data, loading, error } = useAllocation();

  if (loading) {
    return (
      <div className="bg-white rounded-xl border border-slate-200 p-5">
        <div className="flex justify-center py-4"><Spinner /></div>
      </div>
    );
  }
  if (error || !data) return null;

  const { by_sector: rawSectors = [] } = data;
  const sectors = rawSectors
    .map((d) => ({ ...d, weight_pct: Number(d.weight_pct) }))
    .filter((d) => d.weight_pct > 0)
    .sort((a, b) => b.weight_pct - a.weight_pct);

  if (sectors.length === 0) return null;

  return (
    <div className="bg-white rounded-xl border border-slate-200 p-3 sm:p-5">
      <h2 className="text-lg sm:text-xl font-semibold text-slate-800 mb-4">
        Portfolio Allocation
      </h2>

      {/* Stacked horizontal bar */}
      <div className="w-full h-8 rounded-lg overflow-hidden flex mb-4">
        {sectors.map((entry, i) => (
          <div
            key={entry.name}
            style={{
              width: `${entry.weight_pct}%`,
              backgroundColor: getSectorColor(entry.name, i),
            }}
            className="h-full relative group transition-all"
            title={`${entry.name}: ${formatPctUnsigned(entry.weight_pct, 1)}`}
          >
            {entry.weight_pct > 8 && (
              <span className="absolute inset-0 flex items-center justify-center text-white text-xs font-semibold truncate px-1">
                {entry.name}
              </span>
            )}
          </div>
        ))}
      </div>

      {/* Sector pills */}
      <div className="flex flex-wrap gap-2">
        {sectors.map((entry, i) => {
          const color = getSectorColor(entry.name, i);
          return (
            <div
              key={entry.name}
              className="inline-flex items-center gap-2 px-3 py-1.5 rounded-lg border border-slate-200 bg-slate-50 text-sm font-medium text-slate-700"
            >
              <span
                className="w-2.5 h-2.5 rounded-full flex-shrink-0"
                style={{ backgroundColor: color }}
              />
              <span>{entry.name}</span>
              <span className="font-mono tabular-nums font-bold">
                {formatPctUnsigned(entry.weight_pct, 1)}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
