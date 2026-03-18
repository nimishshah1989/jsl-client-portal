'use client';

import { useAllocation } from '@/hooks/usePortfolio';
import { formatPct, formatPctUnsigned } from '@/lib/format';
import { ASSET_CLASS_COLORS, SECTOR_COLORS } from '@/lib/constants';
import {
  PieChart,
  Pie,
  Cell,
  Tooltip,
  ResponsiveContainer,
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Legend,
} from 'recharts';

function Skeleton() {
  return (
    <div className="bg-white rounded-xl border border-slate-200 p-5 animate-pulse">
      <div className="h-5 w-48 bg-slate-200 rounded mb-4" />
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        <div className="h-64 bg-slate-100 rounded-full mx-auto w-64" />
        <div className="h-64 bg-slate-100 rounded-full mx-auto w-64" />
      </div>
    </div>
  );
}

function DonutTooltip({ active, payload }) {
  if (!active || !payload || payload.length === 0) return null;
  const { name, value } = payload[0];
  return (
    <div className="bg-white border border-slate-200 rounded-lg p-2.5 shadow-lg text-sm">
      <p className="font-medium text-slate-700">{name}</p>
      <p className="font-mono text-slate-800">{formatPctUnsigned(value, 1)}</p>
    </div>
  );
}

function DonutLabel({ cx, cy, label }) {
  return (
    <text x={cx} y={cy} textAnchor="middle" dominantBaseline="central">
      <tspan x={cx} dy="-0.5em" className="fill-slate-800 text-sm font-semibold">
        {label}
      </tspan>
    </text>
  );
}

export default function AllocationCharts() {
  const { data, loading, error } = useAllocation();

  if (loading) return <Skeleton />;
  if (error) {
    return (
      <div className="bg-white rounded-xl border border-slate-200 p-5">
        <p className="text-red-600 text-sm">Failed to load allocation data: {error}</p>
      </div>
    );
  }
  if (!data) {
    return (
      <div className="bg-white rounded-xl border border-slate-200 p-5">
        <p className="text-slate-500 text-sm">No allocation data available.</p>
      </div>
    );
  }

  const { by_class: rawByClass = [], by_sector: rawBySector = [], over_time = [] } = data;
  // API returns weight_pct as string — convert to number for Recharts
  const by_class = rawByClass.map((d) => ({ ...d, weight_pct: Number(d.weight_pct) }));
  const by_sector = rawBySector.map((d) => ({ ...d, weight_pct: Number(d.weight_pct) }));

  return (
    <div className="bg-white rounded-xl border border-slate-200 p-3 sm:p-5 overflow-hidden">
      <h2 className="text-lg sm:text-xl font-semibold text-slate-800 mb-4">
        Portfolio Allocation
      </h2>

      <div className={`grid grid-cols-1 ${by_sector.length > 0 ? 'md:grid-cols-2' : ''} gap-6 mb-6`}>
        {/* By asset class donut */}
        <div>
          <h3 className="text-sm font-semibold text-slate-600 mb-3 text-center">By Asset Class</h3>
          <ResponsiveContainer width="100%" height={240}>
            <PieChart>
              <Pie
                data={by_class}
                dataKey="weight_pct"
                nameKey="name"
                cx="50%"
                cy="50%"
                innerRadius={60}
                outerRadius={95}
                paddingAngle={2}
                strokeWidth={0}
              >
                {by_class.map((entry) => (
                  <Cell
                    key={entry.name}
                    fill={ASSET_CLASS_COLORS[entry.name] || '#94a3b8'}
                  />
                ))}
              </Pie>
              <Tooltip content={<DonutTooltip />} />
            </PieChart>
          </ResponsiveContainer>
          <div className="flex flex-wrap justify-center gap-3 mt-2">
            {by_class.map((entry) => (
              <div key={entry.name} className="flex items-center gap-1.5 text-xs text-slate-600">
                <span
                  className="w-2.5 h-2.5 rounded-full"
                  style={{ backgroundColor: ASSET_CLASS_COLORS[entry.name] || '#94a3b8' }}
                />
                {entry.name} ({formatPctUnsigned(entry.weight_pct, 1)})
              </div>
            ))}
          </div>
        </div>

        {/* By sector donut — hidden when no sector data */}
        {by_sector.length > 0 && (
          <div>
            <h3 className="text-sm font-semibold text-slate-600 mb-3 text-center">By Sector</h3>
            <ResponsiveContainer width="100%" height={240}>
              <PieChart>
                <Pie
                  data={by_sector}
                  dataKey="weight_pct"
                  nameKey="name"
                  cx="50%"
                  cy="50%"
                  innerRadius={60}
                  outerRadius={95}
                  paddingAngle={2}
                  strokeWidth={0}
                >
                  {by_sector.map((entry, idx) => (
                    <Cell
                      key={entry.name}
                      fill={SECTOR_COLORS[idx % SECTOR_COLORS.length]}
                    />
                  ))}
                </Pie>
                <Tooltip content={<DonutTooltip />} />
              </PieChart>
            </ResponsiveContainer>
            <div className="flex flex-wrap justify-center gap-3 mt-2">
              {by_sector.slice(0, 8).map((entry, idx) => (
                <div key={entry.name} className="flex items-center gap-1.5 text-xs text-slate-600">
                  <span
                    className="w-2.5 h-2.5 rounded-full"
                    style={{ backgroundColor: SECTOR_COLORS[idx % SECTOR_COLORS.length] }}
                  />
                  {entry.name} ({formatPctUnsigned(entry.weight_pct, 1)})
                </div>
              ))}
              {by_sector.length > 8 && (
                <span className="text-xs text-slate-400">+{by_sector.length - 8} more</span>
              )}
            </div>
          </div>
        )}
      </div>

      {/* Allocation shift over time */}
      {over_time.length > 0 && (
        <div>
          <h3 className="text-sm font-semibold text-slate-600 mb-3">Allocation Over Time</h3>
          <ResponsiveContainer width="100%" height={200} className="sm:!h-[240px]">
            <AreaChart data={over_time} margin={{ top: 5, right: 10, left: 0, bottom: 5 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" vertical={false} />
              <XAxis
                dataKey="date"
                tick={{ fontSize: 11, fill: '#94a3b8' }}
                tickLine={false}
                axisLine={{ stroke: '#e2e8f0' }}
              />
              <YAxis
                tick={{ fontSize: 11, fill: '#94a3b8' }}
                tickLine={false}
                axisLine={false}
                tickFormatter={(v) => `${v}%`}
                domain={[0, 100]}
              />
              {Object.keys(ASSET_CLASS_COLORS).map((cls) => (
                <Area
                  key={cls}
                  type="monotone"
                  dataKey={cls}
                  stackId="1"
                  fill={ASSET_CLASS_COLORS[cls]}
                  stroke={ASSET_CLASS_COLORS[cls]}
                  fillOpacity={0.7}
                />
              ))}
              <Tooltip
                formatter={(value, name) => [`${value != null ? Number(value).toFixed(1) : 0}%`, name]}
                contentStyle={{ borderRadius: 8, border: '1px solid #e2e8f0' }}
              />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  );
}
