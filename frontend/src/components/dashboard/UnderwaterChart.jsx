'use client';

import { useState } from 'react';
import { useDrawdown } from '@/hooks/usePortfolio';
import { formatDateShort, formatPct } from '@/lib/format';
import { CHART_COLORS, TIME_RANGES } from '@/lib/constants';
import {
  AreaChart,
  Area,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
  ComposedChart,
} from 'recharts';

function Skeleton() {
  return (
    <div className="bg-white rounded-xl border border-slate-200 p-5 animate-pulse">
      <div className="h-5 w-56 bg-slate-200 rounded mb-4" />
      <div className="h-64 bg-slate-100 rounded" />
    </div>
  );
}

function CustomTooltip({ active, payload, label }) {
  if (!active || !payload || payload.length === 0) return null;
  return (
    <div className="bg-white border border-slate-200 rounded-lg p-3 shadow-lg text-sm">
      <p className="font-medium text-slate-700 mb-1">{label}</p>
      {payload.map((entry) => (
        <div key={entry.dataKey} className="flex items-center gap-2">
          <span className="w-2.5 h-2.5 rounded-full" style={{ backgroundColor: entry.color }} />
          <span className="text-slate-500">{entry.name}:</span>
          <span className="font-mono font-medium text-slate-800">{formatPct(entry.value)}</span>
        </div>
      ))}
    </div>
  );
}

export default function UnderwaterChart() {
  const [range, setRange] = useState('ALL');
  const { data, loading, error } = useDrawdown(range);

  if (loading) return <Skeleton />;
  if (error) {
    return (
      <div className="bg-white rounded-xl border border-slate-200 p-5">
        <p className="text-red-600 text-sm">Failed to load drawdown data: {error}</p>
      </div>
    );
  }
  if (!data || data.length === 0) {
    return (
      <div className="bg-white rounded-xl border border-slate-200 p-5">
        <p className="text-slate-500 text-sm">No drawdown data available.</p>
      </div>
    );
  }

  const chartData = data.map((d) => ({
    dateLabel: formatDateShort(d.dd_date || d.date),
    drawdown_pct: d.drawdown_pct != null ? Number(d.drawdown_pct) : null,
    bench_drawdown: d.bench_drawdown != null ? Number(d.bench_drawdown) : null,
  }));

  const tickInterval = Math.max(1, Math.floor(chartData.length / 8));

  return (
    <div className="bg-white rounded-xl border border-slate-200 p-5">
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between mb-4 gap-3">
        <h2 className="text-xl font-semibold text-slate-800">
          Underwater Chart (Drawdown %)
        </h2>
        <div className="flex flex-wrap gap-1">
          {TIME_RANGES.map((r) => (
            <button
              key={r}
              onClick={() => setRange(r)}
              className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${
                range === r
                  ? 'bg-jip-teal text-white'
                  : 'bg-slate-100 text-slate-600 hover:bg-slate-200'
              }`}
            >
              {r}
            </button>
          ))}
        </div>
      </div>

      <ResponsiveContainer width="100%" height={300}>
        <ComposedChart data={chartData} margin={{ top: 5, right: 10, left: 0, bottom: 5 }}>
          <defs>
            <linearGradient id="ddGradient" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={CHART_COLORS.negative} stopOpacity={0.3} />
              <stop offset="100%" stopColor={CHART_COLORS.negative} stopOpacity={0.05} />
            </linearGradient>
          </defs>
          <CartesianGrid strokeDasharray="3 3" stroke={CHART_COLORS.grid} vertical={false} />
          <XAxis
            dataKey="dateLabel"
            tick={{ fontSize: 11, fill: '#94a3b8' }}
            tickLine={false}
            axisLine={{ stroke: '#e2e8f0' }}
            interval={tickInterval}
          />
          <YAxis
            tick={{ fontSize: 11, fill: '#94a3b8' }}
            tickLine={false}
            axisLine={false}
            domain={['auto', 0]}
            tickFormatter={(v) => `${Number(v).toFixed(0)}%`}
          />
          <Tooltip content={<CustomTooltip />} />
          <Legend
            verticalAlign="top"
            align="right"
            iconType="plainline"
            wrapperStyle={{ fontSize: 12, paddingBottom: 8 }}
          />
          <Area
            type="monotone"
            dataKey="drawdown_pct"
            name="Portfolio"
            stroke={CHART_COLORS.negative}
            fill="url(#ddGradient)"
            strokeWidth={1.5}
            dot={false}
          />
          <Line
            type="monotone"
            dataKey="bench_drawdown"
            name="NIFTY 50"
            stroke={CHART_COLORS.benchmark}
            strokeWidth={1}
            strokeDasharray="6 3"
            dot={false}
          />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}
