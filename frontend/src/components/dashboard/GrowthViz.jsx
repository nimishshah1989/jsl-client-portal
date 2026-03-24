'use client';

import { useGrowth } from '@/hooks/usePortfolio';
import { formatINRShort, formatPct } from '@/lib/format';
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
  LabelList,
} from 'recharts';

function Skeleton() {
  return (
    <div className="bg-white rounded-xl border border-slate-200 p-5 animate-pulse">
      <div className="h-5 w-56 bg-slate-200 rounded mb-4" />
      <div className="h-64 bg-slate-100 rounded" />
    </div>
  );
}

const BAR_COLORS = {
  Portfolio: CHART_COLORS.portfolio,
  'NIFTY 50': CHART_COLORS.benchmark,
  'Fixed Deposit': '#f59e0b',
  Invested: '#e2e8f0',
};

function CustomTooltip({ active, payload }) {
  if (!active || !payload || payload.length === 0) return null;
  const item = payload[0].payload;
  return (
    <div className="bg-white border border-slate-200 rounded-lg p-3 shadow-lg text-sm">
      <p className="font-medium text-slate-700 mb-1">{item.name}</p>
      <p className="font-mono text-slate-800">{formatINRShort(item.value)}</p>
      {item.return_pct != null && (
        <p className={`text-xs mt-1 ${item.return_pct >= 0 ? 'text-emerald-600' : 'text-red-600'}`}>
          {formatPct(item.return_pct)} return
        </p>
      )}
    </div>
  );
}

export default function GrowthViz() {
  const { data, loading, error } = useGrowth();

  if (loading) return <Skeleton />;
  if (error) {
    return (
      <div className="bg-white rounded-xl border border-slate-200 p-5">
        <p className="text-red-600 text-sm">Failed to load growth data: {error}</p>
      </div>
    );
  }
  if (!data) {
    return (
      <div className="bg-white rounded-xl border border-slate-200 p-5">
        <p className="text-slate-500 text-sm">No growth data available.</p>
      </div>
    );
  }

  const invested = Number(data.invested) || 0;
  const portfolio = Number(data.portfolio) || 0;
  const nifty = Number(data.nifty) || 0;
  const fd = Number(data.fd) || 0;
  const chartData = [
    { name: 'Invested', value: invested, return_pct: null },
    {
      name: 'Portfolio',
      value: portfolio,
      return_pct: invested > 0 ? ((portfolio / invested) - 1) * 100 : 0,
    },
    {
      name: 'NIFTY 50',
      value: nifty,
      return_pct: invested > 0 ? ((nifty / invested) - 1) * 100 : 0,
    },
    {
      name: 'Fixed Deposit',
      value: fd,
      return_pct: invested > 0 ? ((fd / invested) - 1) * 100 : 0,
    },
  ];

  // Y-axis domain: start from 0, add 15% headroom above max for label space
  const maxVal = Math.max(...chartData.map((d) => d.value));
  const yMax = Math.ceil(maxVal * 1.15);

  return (
    <div className="bg-white rounded-xl border border-slate-200 p-3 sm:p-5 overflow-hidden">
      <h2 className="text-lg sm:text-xl font-semibold text-slate-800 mb-1">
        What Your Money Became
      </h2>
      <p className="text-xs sm:text-sm text-slate-500 mb-4">
        {formatINRShort(invested)} invested &mdash; comparison across instruments
      </p>

      <ResponsiveContainer width="100%" height={260} className="sm:!h-[300px]">
        <BarChart
          data={chartData}
          margin={{ top: 30, right: 20, left: 10, bottom: 5 }}
          barCategoryGap="25%"
        >
          <CartesianGrid strokeDasharray="3 3" stroke={CHART_COLORS.grid} vertical={false} />
          <XAxis
            dataKey="name"
            tick={{ fontSize: 12, fill: '#64748b', fontWeight: 500 }}
            tickLine={false}
            axisLine={{ stroke: '#e2e8f0' }}
          />
          <YAxis
            tick={{ fontSize: 10, fill: '#94a3b8' }}
            tickLine={false}
            axisLine={false}
            domain={[0, yMax]}
            tickFormatter={(v) => formatINRShort(v)}
            width={65}
          />
          <Tooltip content={<CustomTooltip />} />
          <Bar dataKey="value" radius={[6, 6, 0, 0]} maxBarSize={80} barSize={50}>
            {chartData.map((entry) => (
              <Cell key={entry.name} fill={BAR_COLORS[entry.name] || '#94a3b8'} />
            ))}
            <LabelList
              dataKey="value"
              position="top"
              formatter={(v) => formatINRShort(v)}
              className="text-xs fill-slate-600 font-mono"
              offset={8}
            />
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
