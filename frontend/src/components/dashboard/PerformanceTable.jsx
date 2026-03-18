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
  {
    key: 'abs_return',
    label: 'Absolute Return',
    description: 'Total percentage gain or loss over the period. Formula: (End Value / Start Value - 1) × 100',
  },
  {
    key: 'cagr',
    label: 'CAGR',
    description: 'Compound Annual Growth Rate — annualized return that accounts for compounding. Normalizes returns across different time periods for fair comparison.',
  },
  {
    key: 'volatility',
    label: 'Volatility',
    description: 'Annualized standard deviation of daily returns (×√252). Higher volatility = larger daily swings. Measures total risk, both up and down.',
  },
  {
    key: 'max_dd',
    label: 'Max Drawdown',
    description: 'Largest peak-to-trough decline during the period. Shows the worst-case scenario an investor would have experienced.',
  },
  {
    key: 'sharpe',
    label: 'Sharpe Ratio',
    description: 'Risk-adjusted return: (Return - Risk Free Rate) / Volatility. Higher is better. >1 = good, >2 = excellent. Uses 7% risk-free rate (India 10Y bond).',
  },
  {
    key: 'sortino',
    label: 'Sortino Ratio',
    description: 'Like Sharpe but only penalizes downside volatility. Better for portfolios that have more upside than downside movement. Higher is better.',
  },
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
                <span className="inline-flex items-center gap-1">
                  {metric.label}
                  <span className="relative group">
                    <span className="text-slate-400 hover:text-slate-600 cursor-default select-none text-xs leading-none">
                      ⓘ
                    </span>
                    <span className="absolute left-0 top-5 z-50 hidden group-hover:block w-[280px] rounded-lg bg-white border border-slate-200 shadow-lg px-3 py-2 text-xs text-slate-600 font-normal leading-relaxed">
                      {metric.description}
                    </span>
                  </span>
                </span>
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
                        ? (portVal != null ? Number(portVal).toFixed(2) : '--')
                        : formatPct(portVal)}
                    </td>
                    <td className={`text-center px-2 py-2.5 font-mono tabular-nums text-xs text-slate-400`}>
                      {isRatio
                        ? (benchVal != null ? Number(benchVal).toFixed(2) : '--')
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
