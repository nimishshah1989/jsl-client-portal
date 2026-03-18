'use client';

import React from 'react';
import { usePerformanceTable } from '@/hooks/usePortfolio';
import { formatPct, pnlColor } from '@/lib/format';

function Skeleton() {
  return (
    <div className="bg-white rounded-xl border border-slate-200 p-5 animate-pulse">
      <div className="h-5 w-64 bg-slate-200 rounded mb-4" />
      <div className="space-y-3">
        {Array.from({ length: 6 }).map((_, i) => (
          <div key={i} className="h-10 bg-slate-100 rounded" />
        ))}
      </div>
    </div>
  );
}

const METRIC_LABELS = [
  { key: 'abs_return', label: 'Absolute Return' },
  { key: 'cagr', label: 'CAGR' },
  { key: 'volatility', label: 'Volatility' },
  { key: 'max_dd', label: 'Max Drawdown' },
  { key: 'sharpe', label: 'Sharpe Ratio' },
  { key: 'sortino', label: 'Sortino Ratio' },
];

export default function PerformanceTable() {
  const { data, loading, error } = usePerformanceTable();

  if (loading) return <Skeleton />;
  if (error) {
    return (
      <div className="bg-white rounded-xl border border-slate-200 p-5">
        <p className="text-red-600 text-sm">Failed to load performance data: {error}</p>
      </div>
    );
  }
  if (!data || data.length === 0) {
    return (
      <div className="bg-white rounded-xl border border-slate-200 p-5">
        <p className="text-slate-500 text-sm">No performance data available.</p>
      </div>
    );
  }

  // data is an array of period objects
  const periods = data;

  return (
    <div className="bg-white rounded-xl border border-slate-200 p-5 overflow-x-auto">
      <h2 className="text-xl font-semibold text-slate-800 mb-4">
        Performance Summary &mdash; Portfolio vs NIFTY 50
      </h2>

      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-slate-200">
            <th className="text-left text-xs font-semibold text-slate-400 uppercase tracking-wider px-3 py-2">
              Metric
            </th>
            {periods.map((p) => (
              <th
                key={p.period}
                className="text-center text-xs font-semibold text-slate-400 uppercase tracking-wider px-3 py-2"
                colSpan={2}
              >
                {p.period}
              </th>
            ))}
          </tr>
          <tr className="border-b border-slate-100">
            <th />
            {periods.map((p) => (
              <React.Fragment key={p.period}>
                <th className="text-center text-xs text-teal-600 font-medium px-2 py-1">Port</th>
                <th className="text-center text-xs text-slate-400 font-medium px-2 py-1">Bench</th>
              </React.Fragment>
            ))}
          </tr>
        </thead>
        <tbody>
          {METRIC_LABELS.map((metric) => (
            <tr key={metric.key} className="border-b border-slate-50 hover:bg-slate-50">
              <td className="px-3 py-2.5 font-medium text-slate-700 whitespace-nowrap">
                {metric.label}
              </td>
              {periods.map((p) => {
                const portKey = `port_${metric.key}`;
                const benchKey = `bench_${metric.key}`;
                const portVal = p[portKey];
                const benchVal = p[benchKey];
                const isRatio = metric.key === 'sharpe' || metric.key === 'sortino';

                return (
                  <React.Fragment key={p.period}>
                    <td className={`text-center px-2 py-2.5 font-mono tabular-nums text-xs ${isRatio ? '' : pnlColor(portVal)}`}>
                      {isRatio
                        ? (portVal != null ? portVal.toFixed(2) : '--')
                        : formatPct(portVal)}
                    </td>
                    <td className={`text-center px-2 py-2.5 font-mono tabular-nums text-xs text-slate-400`}>
                      {isRatio
                        ? (benchVal != null ? benchVal.toFixed(2) : '--')
                        : formatPct(benchVal)}
                    </td>
                  </React.Fragment>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
