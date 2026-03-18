'use client';

import { useState } from 'react';
import { useNavSeries } from '@/hooks/usePortfolio';
import { formatDateShort, formatPct } from '@/lib/format';
import { CHART_COLORS, TIME_RANGES } from '@/lib/constants';
import {
  ComposedChart,
  Area,
  Line,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from 'recharts';

function ChartSkeleton() {
  return (
    <div className="bg-white rounded-xl border border-slate-200 p-5">
      <div className="animate-pulse">
        <div className="h-5 w-56 bg-slate-200 rounded mb-4" />
        <div className="flex gap-2 mb-4">
          {Array.from({ length: 8 }).map((_, i) => (
            <div key={i} className="h-8 w-10 bg-slate-200 rounded" />
          ))}
        </div>
        <div className="h-72 bg-slate-100 rounded" />
      </div>
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
          <span
            className="w-2.5 h-2.5 rounded-full"
            style={{ backgroundColor: entry.color }}
          />
          <span className="text-slate-500">{entry.name}:</span>
          <span className="font-mono font-medium text-slate-800">
            {entry.dataKey === 'cash_pct'
              ? `${entry.value?.toFixed(1)}%`
              : entry.value?.toFixed(2)}
          </span>
        </div>
      ))}
    </div>
  );
}

export default function NavChart() {
  const [range, setRange] = useState('ALL');
  const { data, loading, error } = useNavSeries(range);

  if (loading) return <ChartSkeleton />;

  if (error) {
    return (
      <div className="bg-white rounded-xl border border-slate-200 p-5">
        <p className="text-red-600 text-sm">Failed to load chart: {error}</p>
      </div>
    );
  }

  if (!data || data.length === 0) {
    return (
      <div className="bg-white rounded-xl border border-slate-200 p-5">
        <p className="text-slate-500 text-sm">No NAV data available.</p>
      </div>
    );
  }

  // Format data for display
  const chartData = data.map((d) => ({
    ...d,
    dateLabel: formatDateShort(d.date),
  }));

  // Compute tick interval to avoid overcrowding
  const tickInterval = Math.max(1, Math.floor(chartData.length / 8));

  return (
    <div className="bg-white rounded-xl border border-slate-200 p-5">
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between mb-4 gap-3">
        <h2 className="text-xl font-semibold text-slate-800">
          Relative Performance (Base 100)
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

      <ResponsiveContainer width="100%" height={360}>
        <ComposedChart
          data={chartData}
          margin={{ top: 5, right: 10, left: 0, bottom: 5 }}
        >
          <defs>
            <linearGradient id="navGradient" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={CHART_COLORS.portfolio} stopOpacity={0.15} />
              <stop offset="100%" stopColor={CHART_COLORS.portfolio} stopOpacity={0.02} />
            </linearGradient>
          </defs>
          <CartesianGrid
            strokeDasharray="3 3"
            stroke={CHART_COLORS.grid}
            vertical={false}
          />
          <XAxis
            dataKey="dateLabel"
            tick={{ fontSize: 11, fill: '#94a3b8' }}
            tickLine={false}
            axisLine={{ stroke: '#e2e8f0' }}
            interval={tickInterval}
          />
          <YAxis
            yAxisId="nav"
            tick={{ fontSize: 11, fill: '#94a3b8' }}
            tickLine={false}
            axisLine={false}
            domain={['auto', 'auto']}
          />
          <YAxis
            yAxisId="cash"
            orientation="right"
            tick={{ fontSize: 11, fill: '#d97706' }}
            tickLine={false}
            axisLine={false}
            domain={[0, 'auto']}
            tickFormatter={(v) => `${v}%`}
          />
          <Tooltip content={<CustomTooltip />} />
          <Legend
            verticalAlign="top"
            align="right"
            iconType="plainline"
            wrapperStyle={{ fontSize: 12, paddingBottom: 8 }}
          />
          <Area
            yAxisId="nav"
            type="monotone"
            dataKey="nav"
            name="Portfolio"
            stroke={CHART_COLORS.portfolio}
            strokeWidth={2}
            fill="url(#navGradient)"
            dot={false}
            activeDot={{ r: 4, strokeWidth: 0, fill: CHART_COLORS.portfolio }}
          />
          <Line
            yAxisId="nav"
            type="monotone"
            dataKey="benchmark"
            name="NIFTY 50"
            stroke={CHART_COLORS.benchmark}
            strokeWidth={1.5}
            strokeDasharray="6 3"
            dot={false}
            activeDot={{ r: 3, strokeWidth: 0, fill: CHART_COLORS.benchmark }}
          />
          <Bar
            yAxisId="cash"
            dataKey="cash_pct"
            name="Cash %"
            fill={CHART_COLORS.cashFill}
            barSize={3}
            radius={[1, 1, 0, 0]}
          />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}
