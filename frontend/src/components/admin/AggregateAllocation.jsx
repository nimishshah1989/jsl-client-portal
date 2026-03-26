'use client';

import { useAggregateAllocation } from '@/hooks/useAggregate';
import { formatPctUnsigned, formatINRShort } from '@/lib/format';
import { SECTOR_COLORS } from '@/lib/constants';
import {
  PieChart,
  Pie,
  Cell,
  Tooltip,
  ResponsiveContainer,
} from 'recharts';
import Spinner from '@/components/ui/Spinner';

const FALLBACK_COLORS = [
  '#0d9488', '#6366f1', '#ec4899', '#f59e0b', '#3b82f6',
  '#22c55e', '#ef4444', '#8b5cf6', '#f97316', '#06b6d4',
  '#84cc16', '#d946ef', '#78716c', '#0ea5e9', '#a855f7',
];

function getSectorColor(name, index) {
  return SECTOR_COLORS[name] || FALLBACK_COLORS[index % FALLBACK_COLORS.length];
}

function Skeleton() {
  return (
    <div className="bg-white rounded-xl border border-slate-200 p-5 animate-pulse">
      <div className="h-5 w-52 bg-slate-200 rounded mb-4" />
      <div className="h-64 bg-slate-100 rounded" />
    </div>
  );
}

function CustomTooltip({ active, payload }) {
  if (!active || !payload || payload.length === 0) return null;
  const entry = payload[0];
  return (
    <div className="bg-white border border-slate-200 rounded-lg p-3 shadow-lg text-sm">
      <div className="flex items-center gap-2">
        <span
          className="w-2.5 h-2.5 rounded-full flex-shrink-0"
          style={{ backgroundColor: entry.payload.fill }}
        />
        <span className="font-medium text-slate-700">{entry.name}</span>
      </div>
      <p className="font-mono text-slate-800 mt-1">
        {formatPctUnsigned(entry.value, 1)}
      </p>
      {entry.payload.current_value != null && (
        <p className="text-xs text-slate-400">
          {formatINRShort(entry.payload.current_value)}
        </p>
      )}
    </div>
  );
}

export default function AggregateAllocation() {
  const { data, loading, error } = useAggregateAllocation();

  if (loading) return <Skeleton />;
  if (error) {
    return (
      <div className="bg-white rounded-xl border border-slate-200 p-5">
        <p className="text-red-600 text-sm">Failed to load allocation: {error}</p>
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

  const { by_sector: rawSectors = [] } = data;
  const sectors = rawSectors
    .map((d) => ({ ...d, weight_pct: Number(d.weight_pct) }))
    .filter((d) => d.weight_pct > 0)
    .sort((a, b) => b.weight_pct - a.weight_pct);

  if (sectors.length === 0) {
    return (
      <div className="bg-white rounded-xl border border-slate-200 p-5">
        <p className="text-slate-500 text-sm">No allocation data available.</p>
      </div>
    );
  }

  const pieData = sectors.map((s, i) => ({
    name: s.name,
    value: s.weight_pct,
    current_value: s.current_value,
    fill: getSectorColor(s.name, i),
  }));

  return (
    <div className="bg-white rounded-xl border border-slate-200 p-3 sm:p-5 overflow-hidden">
      <h2 className="text-lg sm:text-xl font-semibold text-slate-800 mb-4">
        Aggregate Sector Allocation
      </h2>

      <div className="flex flex-col lg:flex-row gap-4">
        {/* Donut chart */}
        <div className="flex-shrink-0">
          <ResponsiveContainer width={220} height={220}>
            <PieChart>
              <Pie
                data={pieData}
                dataKey="value"
                nameKey="name"
                cx="50%"
                cy="50%"
                innerRadius={55}
                outerRadius={95}
                paddingAngle={1}
                stroke="none"
              >
                {pieData.map((entry, i) => (
                  <Cell key={entry.name} fill={entry.fill} />
                ))}
              </Pie>
              <Tooltip content={<CustomTooltip />} />
            </PieChart>
          </ResponsiveContainer>
        </div>

        {/* Sector breakdown table */}
        <div className="flex-1 overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-200">
                <th className="text-left text-xs font-semibold text-slate-400 uppercase tracking-wider px-2 py-1.5">
                  Sector
                </th>
                <th className="text-right text-xs font-semibold text-slate-400 uppercase tracking-wider px-2 py-1.5">
                  Weight
                </th>
                {sectors[0]?.current_value != null && (
                  <th className="text-right text-xs font-semibold text-slate-400 uppercase tracking-wider px-2 py-1.5">
                    Value
                  </th>
                )}
              </tr>
            </thead>
            <tbody>
              {sectors.map((s, i) => (
                <tr key={s.name} className="border-b border-slate-50 hover:bg-slate-50">
                  <td className="px-2 py-1.5">
                    <div className="flex items-center gap-2">
                      <span
                        className="w-2.5 h-2.5 rounded-full flex-shrink-0"
                        style={{ backgroundColor: getSectorColor(s.name, i) }}
                      />
                      <span className="text-slate-700">{s.name}</span>
                    </div>
                  </td>
                  <td className="text-right px-2 py-1.5 font-mono tabular-nums font-medium text-slate-800">
                    {formatPctUnsigned(s.weight_pct, 1)}
                  </td>
                  {s.current_value != null && (
                    <td className="text-right px-2 py-1.5 font-mono tabular-nums text-slate-600 text-xs">
                      {formatINRShort(s.current_value)}
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
