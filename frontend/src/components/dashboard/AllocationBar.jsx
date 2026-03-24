'use client';

import { useAllocation } from '@/hooks/usePortfolio';
import { formatPctUnsigned } from '@/lib/format';
import Spinner from '@/components/ui/Spinner';

/**
 * Sector-based allocation mapping.
 * Maps raw asset_class/sector names to display categories with colors.
 */
const SECTOR_DISPLAY = {
  Equity: { color: '#0d9488', bg: 'bg-teal-50 border-teal-200 text-teal-700' },
  Cash: { color: '#d97706', bg: 'bg-amber-50 border-amber-200 text-amber-700' },
  Debt: { color: '#6366f1', bg: 'bg-indigo-50 border-indigo-200 text-indigo-700' },
  Gold: { color: '#ca8a04', bg: 'bg-yellow-50 border-yellow-200 text-yellow-700' },
  Metals: { color: '#ca8a04', bg: 'bg-yellow-50 border-yellow-200 text-yellow-700' },
  Others: { color: '#94a3b8', bg: 'bg-slate-50 border-slate-200 text-slate-600' },
  OTHER: { color: '#94a3b8', bg: 'bg-slate-50 border-slate-200 text-slate-600' },
};

function getStyle(name) {
  return SECTOR_DISPLAY[name] || SECTOR_DISPLAY.Others;
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

  const { by_class: rawByClass = [] } = data;
  const by_class = rawByClass
    .map((d) => ({ ...d, weight_pct: Number(d.weight_pct) }))
    .filter((d) => d.weight_pct > 0)
    .sort((a, b) => b.weight_pct - a.weight_pct);

  if (by_class.length === 0) return null;

  return (
    <div className="bg-white rounded-xl border border-slate-200 p-3 sm:p-5">
      <h2 className="text-lg sm:text-xl font-semibold text-slate-800 mb-4">
        Portfolio Allocation
      </h2>

      {/* Stacked horizontal bar */}
      <div className="w-full h-8 rounded-lg overflow-hidden flex mb-4">
        {by_class.map((entry) => (
          <div
            key={entry.name}
            style={{
              width: `${entry.weight_pct}%`,
              backgroundColor: getStyle(entry.name).color,
            }}
            className="h-full relative group transition-all"
            title={`${entry.name}: ${formatPctUnsigned(entry.weight_pct, 1)}`}
          >
            {entry.weight_pct > 8 && (
              <span className="absolute inset-0 flex items-center justify-center text-white text-xs font-semibold">
                {entry.name}
              </span>
            )}
          </div>
        ))}
      </div>

      {/* Category pills */}
      <div className="flex flex-wrap gap-2">
        {by_class.map((entry) => {
          const style = getStyle(entry.name);
          return (
            <div
              key={entry.name}
              className={`inline-flex items-center gap-2 px-3 py-1.5 rounded-lg border text-sm font-medium ${style.bg}`}
            >
              <span
                className="w-2.5 h-2.5 rounded-full flex-shrink-0"
                style={{ backgroundColor: style.color }}
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
