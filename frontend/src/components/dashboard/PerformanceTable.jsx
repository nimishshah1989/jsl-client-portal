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
    label: 'Abs Return',
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
    label: 'Max DD',
    description: 'Largest peak-to-trough decline during the period. Shows the worst-case scenario an investor would have experienced.',
  },
  {
    key: 'sharpe',
    label: 'Sharpe',
    description: 'Risk-adjusted return: (Return - Risk Free Rate) / Volatility. Higher is better. >1 = good, >2 = excellent. Uses 6.50% risk-free rate (India 10Y bond).',
  },
  {
    key: 'sortino',
    label: 'Sortino',
    description: 'Like Sharpe but only penalizes downside volatility. Better for portfolios that have more upside than downside movement. Higher is better.',
  },
];

function CellValue({ metric, value, isBench }) {
  const isRatio = metric === 'sharpe' || metric === 'sortino';
  if (isBench) {
    return (
      <span className="text-slate-400">
        {isRatio
          ? (value != null ? Number(value).toFixed(2) : '--')
          : formatPct(value)}
      </span>
    );
  }
  return (
    <span className={isRatio ? '' : pnlColor(value)}>
      {isRatio
        ? (value != null ? Number(value).toFixed(2) : '--')
        : formatPct(value)}
    </span>
  );
}

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

  const periods = data;

  return (
    <div className="bg-white rounded-xl border border-slate-200 p-3 sm:p-5">
      <h2 className="text-lg sm:text-xl font-semibold text-slate-800 mb-4">
        Performance Summary &mdash; Portfolio vs NIFTY 50
      </h2>

      <div className="relative">
        <div className="overflow-x-auto -mx-3 px-3 sm:-mx-5 sm:px-5" style={{ WebkitOverflowScrolling: 'touch' }}>
          <div className="pointer-events-none absolute right-0 top-0 bottom-0 w-8 bg-gradient-to-l from-white to-transparent z-10 sm:hidden" />
          <table className="w-full text-sm min-w-[700px]">
            <thead>
              <tr className="border-b border-slate-200">
                <th className="text-left text-xs font-semibold text-slate-400 uppercase tracking-wider px-3 py-2">
                  Period
                </th>
                {METRIC_LABELS.map((m) => (
                  <th
                    key={m.key}
                    className="text-center text-xs font-semibold text-slate-400 uppercase tracking-wider px-2 py-2"
                    colSpan={2}
                  >
                    <span className="inline-flex items-center gap-1">
                      {m.label}
                      <span className="relative group">
                        <span className="text-slate-400 hover:text-slate-600 cursor-default select-none leading-none">
                          ⓘ
                        </span>
                        <span className="absolute left-1/2 -translate-x-1/2 top-5 z-50 hidden group-hover:block w-[220px] sm:w-[260px] rounded-lg bg-white border border-slate-200 shadow-lg px-3 py-2 text-xs text-slate-600 font-normal leading-relaxed text-left normal-case tracking-normal">
                          {m.description}
                        </span>
                      </span>
                    </span>
                  </th>
                ))}
              </tr>
              <tr className="border-b border-slate-100">
                <th />
                {METRIC_LABELS.map((m) => (
                  <React.Fragment key={m.key}>
                    <th className="text-center text-xs text-teal-600 font-medium px-1 py-1">Port</th>
                    <th className="text-center text-xs text-slate-400 font-medium px-1 py-1">Bench</th>
                  </React.Fragment>
                ))}
              </tr>
            </thead>
            <tbody>
              {periods.map((p) => (
                <tr key={p.period} className="border-b border-slate-50 hover:bg-slate-50">
                  <td className="px-3 py-2.5 font-medium text-slate-700 whitespace-nowrap">
                    {p.period}
                  </td>
                  {METRIC_LABELS.map((metric) => {
                    const portVal = p[`port_${metric.key}`];
                    const benchVal = p[`bench_${metric.key}`];
                    return (
                      <React.Fragment key={metric.key}>
                        <td className="text-center px-1 py-2.5 font-mono tabular-nums text-xs">
                          <CellValue metric={metric.key} value={portVal} isBench={false} />
                        </td>
                        <td className="text-center px-1 py-2.5 font-mono tabular-nums text-xs">
                          <CellValue metric={metric.key} value={benchVal} isBench={true} />
                        </td>
                      </React.Fragment>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="text-xs text-slate-400 mt-2 sm:hidden">Scroll sideways to see all metrics</p>
      </div>
    </div>
  );
}
