'use client';

import { useRiskScorecard } from '@/hooks/usePortfolio';
import { formatPct } from '@/lib/format';
import { CHART_COLORS } from '@/lib/constants';
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Cell,
  ReferenceLine,
} from 'recharts';

function Skeleton() {
  return (
    <div className="bg-white rounded-xl border border-slate-200 p-5 animate-pulse">
      <div className="h-5 w-52 bg-slate-200 rounded mb-4" />
      <div className="h-64 bg-slate-100 rounded" />
    </div>
  );
}

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

function HeatmapGrid({ monthlyData = [] }) {
  if (!monthlyData || monthlyData.length === 0) {
    return <p className="text-sm text-slate-400">No monthly return data available.</p>;
  }

  // Group by year
  const years = {};
  monthlyData.forEach((item) => {
    const year = item.year || new Date(item.date).getFullYear();
    const month = item.month != null ? item.month : new Date(item.date).getMonth();
    if (!years[year]) years[year] = {};
    years[year][month] = item.return_pct;
  });

  const sortedYears = Object.keys(years).sort((a, b) => Number(b) - Number(a));

  function getCellColor(val) {
    if (val == null) return 'bg-slate-50';
    if (val > 5) return 'bg-emerald-500 text-white';
    if (val > 2) return 'bg-emerald-300 text-emerald-900';
    if (val > 0) return 'bg-emerald-100 text-emerald-700';
    if (val > -2) return 'bg-red-100 text-red-700';
    if (val > -5) return 'bg-red-300 text-red-900';
    return 'bg-red-500 text-white';
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs">
        <thead>
          <tr>
            <th className="px-2 py-1.5 text-left text-slate-400 font-semibold">Year</th>
            {MONTHS.map((m) => (
              <th key={m} className="px-1.5 py-1.5 text-center text-slate-400 font-semibold">{m}</th>
            ))}
            <th className="px-2 py-1.5 text-center text-slate-400 font-semibold">Total</th>
          </tr>
        </thead>
        <tbody>
          {sortedYears.map((year) => {
            const monthValues = years[year];
            const total = Object.values(monthValues).reduce((sum, v) => sum + (v || 0), 0);
            return (
              <tr key={year}>
                <td className="px-2 py-1 font-medium text-slate-700">{year}</td>
                {Array.from({ length: 12 }).map((_, i) => {
                  const val = monthValues[i];
                  return (
                    <td key={i} className="px-0.5 py-0.5">
                      <div
                        className={`rounded px-1.5 py-1 text-center font-mono tabular-nums ${getCellColor(val)}`}
                      >
                        {val != null ? `${Number(val) >= 0 ? '+' : ''}${Number(val).toFixed(1)}` : ''}
                      </div>
                    </td>
                  );
                })}
                <td className="px-1 py-0.5">
                  <div className={`rounded px-1.5 py-1 text-center font-mono tabular-nums font-medium ${getCellColor(total)}`}>
                    {total >= 0 ? '+' : ''}{Number(total).toFixed(1)}
                  </div>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

export default function MonthlyReturns() {
  const { data, loading, error } = useRiskScorecard();

  if (loading) return <Skeleton />;
  if (error) {
    return (
      <div className="bg-white rounded-xl border border-slate-200 p-5">
        <p className="text-red-600 text-sm">Failed to load monthly data: {error}</p>
      </div>
    );
  }
  if (!data) {
    return (
      <div className="bg-white rounded-xl border border-slate-200 p-5">
        <p className="text-slate-500 text-sm">No monthly return data available.</p>
      </div>
    );
  }

  const {
    monthly_hit_rate,
    best_month,
    worst_month,
    avg_positive_month,
    avg_negative_month,
    win_count,
    loss_count,
    monthly_returns = [],
  } = data;

  // Win/loss bar data
  const winLossData = [
    { name: 'Winning', value: win_count || 0 },
    { name: 'Losing', value: loss_count || 0 },
  ];

  // Monthly returns for bar chart (last 24 months)
  const recentMonthly = (monthly_returns || []).slice(-24);

  return (
    <div className="bg-white rounded-xl border border-slate-200 p-5">
      <h2 className="text-xl font-semibold text-slate-800 mb-4">
        Monthly Return Profile
      </h2>

      {/* Summary stats */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-3 mb-6">
        <div className="bg-slate-50 rounded-xl p-3">
          <p className="text-xs text-slate-500">Hit Rate</p>
          <p className="text-lg font-bold font-mono text-teal-600">
            {monthly_hit_rate != null ? `${Number(monthly_hit_rate).toFixed(1)}%` : '--'}
          </p>
        </div>
        <div className="bg-slate-50 rounded-xl p-3">
          <p className="text-xs text-slate-500">Best Month</p>
          <p className="text-lg font-bold font-mono text-emerald-600">
            {best_month != null ? formatPct(best_month) : '--'}
          </p>
        </div>
        <div className="bg-slate-50 rounded-xl p-3">
          <p className="text-xs text-slate-500">Worst Month</p>
          <p className="text-lg font-bold font-mono text-red-600">
            {worst_month != null ? formatPct(worst_month) : '--'}
          </p>
        </div>
        <div className="bg-slate-50 rounded-xl p-3">
          <p className="text-xs text-slate-500">Avg Win</p>
          <p className="text-lg font-bold font-mono text-emerald-600">
            {avg_positive_month != null ? formatPct(avg_positive_month) : '--'}
          </p>
        </div>
        <div className="bg-slate-50 rounded-xl p-3">
          <p className="text-xs text-slate-500">Avg Loss</p>
          <p className="text-lg font-bold font-mono text-red-600">
            {avg_negative_month != null ? formatPct(avg_negative_month) : '--'}
          </p>
        </div>
      </div>

      {/* Win/Loss bar chart */}
      {recentMonthly.length > 0 && (
        <div className="mb-6">
          <h3 className="text-sm font-semibold text-slate-600 mb-3">Monthly Returns (Last 24 Months)</h3>
          <ResponsiveContainer width="100%" height={200}>
            <BarChart data={recentMonthly} margin={{ top: 5, right: 10, left: 0, bottom: 5 }}>
              <CartesianGrid strokeDasharray="3 3" stroke={CHART_COLORS.grid} vertical={false} />
              <XAxis
                dataKey="label"
                tick={{ fontSize: 10, fill: '#94a3b8' }}
                tickLine={false}
                axisLine={{ stroke: '#e2e8f0' }}
              />
              <YAxis
                tick={{ fontSize: 11, fill: '#94a3b8' }}
                tickLine={false}
                axisLine={false}
                tickFormatter={(v) => `${v}%`}
              />
              <ReferenceLine y={0} stroke="#e2e8f0" />
              <Tooltip
                formatter={(v) => [formatPct(v), 'Return']}
                contentStyle={{ borderRadius: 8, border: '1px solid #e2e8f0', fontSize: 12 }}
              />
              <Bar dataKey="return_pct" radius={[3, 3, 0, 0]} maxBarSize={16}>
                {recentMonthly.map((entry, idx) => (
                  <Cell
                    key={idx}
                    fill={entry.return_pct >= 0 ? CHART_COLORS.positive : CHART_COLORS.negative}
                  />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* Monthly heatmap grid */}
      <div>
        <h3 className="text-sm font-semibold text-slate-600 mb-3">Monthly Returns Heatmap</h3>
        <HeatmapGrid monthlyData={monthly_returns} />
      </div>
    </div>
  );
}
