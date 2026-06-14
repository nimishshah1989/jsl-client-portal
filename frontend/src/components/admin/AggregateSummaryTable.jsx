'use client';

import { useAggregateSummaryTable } from '@/hooks/useAggregate';
import { formatINRShort, formatPct, pnlColor } from '@/lib/format';
import { Table2 } from 'lucide-react';

const BUCKETS = [
  { key: 'COMBINED', label: 'Combined' },
  { key: 'LEADERS', label: 'Leaders' },
  { key: 'PASSIVE', label: 'Passive' },
  { key: 'IND11', label: 'IND11' },
];

// Rows = key variables; columns = strategy buckets. So the fund manager sees
// everything across strategies at a glance, without toggling.
const ROWS = [
  { key: 'total_aum', label: 'Total AUM', fmt: 'inr' },
  { key: 'cagr', label: 'CAGR', fmt: 'pct' },
  { key: 'deposits_30d', label: 'Deposits (30d)', fmt: 'inr' },
  { key: 'withdrawals_30d', label: 'Withdrawals (30d)', fmt: 'inr' },
  { key: 'max_drawdown', label: 'Max Drawdown', fmt: 'pct' },
];

function Skeleton() {
  return (
    <div className="bg-white rounded-xl border border-slate-200 p-5 animate-pulse">
      <div className="h-5 w-48 bg-slate-200 rounded mb-4" />
      <div className="space-y-3">
        {Array.from({ length: 5 }).map((_, i) => (
          <div key={i} className="h-8 bg-slate-100 rounded" />
        ))}
      </div>
    </div>
  );
}

export default function AggregateSummaryTable({ includeInactive = false }) {
  const { data, loading, error } = useAggregateSummaryTable(includeInactive);

  if (loading) return <Skeleton />;
  if (error || !data?.buckets) return null;
  const buckets = data.buckets;

  function render(row, bKey) {
    const raw = buckets[bKey]?.[row.key];
    if (raw == null) return '—';
    if (row.fmt === 'inr') return formatINRShort(raw);
    if (row.fmt === 'pct') return formatPct(Number(raw));
    return raw;
  }

  return (
    <div className="bg-white rounded-xl border border-slate-200 p-5">
      <div className="flex items-center gap-2 mb-4">
        <Table2 className="w-5 h-5 text-teal-600" />
        <h3 className="text-lg font-bold text-slate-800">Strategy Summary</h3>
        <span className="text-xs text-slate-400 ml-1">
          Rolling {data.window_days || 30}-day flows ·{' '}
          {includeInactive ? 'all portfolios' : 'active portfolios only'}
        </span>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-slate-200">
              <th className="text-left py-2 pr-4 text-xs font-semibold text-slate-400 uppercase tracking-wider">
                Metric
              </th>
              {BUCKETS.map((b) => (
                <th
                  key={b.key}
                  className="text-right py-2 px-3 text-xs font-semibold text-slate-400 uppercase tracking-wider"
                >
                  {b.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {ROWS.map((row) => (
              <tr key={row.key} className="border-b border-slate-100 last:border-0">
                <td className="py-2.5 pr-4 text-slate-600 font-medium">{row.label}</td>
                {BUCKETS.map((b) => {
                  const raw = buckets[b.key]?.[row.key];
                  const color =
                    row.fmt === 'pct' && raw != null ? pnlColor(Number(raw)) : 'text-slate-800';
                  return (
                    <td
                      key={b.key}
                      className={`py-2.5 px-3 text-right font-mono tabular-nums ${color}`}
                    >
                      {render(row, b.key)}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
