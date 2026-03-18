'use client';

import { useState } from 'react';
import { useHoldings } from '@/hooks/usePortfolio';
import { formatINR, formatINRShort, formatPct, pnlColor } from '@/lib/format';
import { ASSET_CLASS_COLORS } from '@/lib/constants';
import { ChevronUp, ChevronDown, ChevronsUpDown, Filter } from 'lucide-react';

function Skeleton() {
  return (
    <div className="bg-white rounded-xl border border-slate-200 p-5 animate-pulse">
      <div className="h-5 w-40 bg-slate-200 rounded mb-4" />
      <div className="space-y-3">
        {Array.from({ length: 8 }).map((_, i) => (
          <div key={i} className="h-10 bg-slate-100 rounded" />
        ))}
      </div>
    </div>
  );
}

const ASSET_CLASSES = ['ALL', 'Equity', 'Cash', 'Debt', 'Gold', 'Others'];

export default function HoldingsTable() {
  const [sort, setSort] = useState('weight_pct');
  const [order, setOrder] = useState('desc');
  const [assetClass, setAssetClass] = useState('ALL');
  // Map frontend field names to backend-accepted sort keys
  const SORT_MAP = {
    weight_pct: 'weight', unrealized_pnl: 'pnl', current_value: 'value',
    symbol: 'name', asset_name: 'name', asset_class: 'class',
    quantity: 'quantity', avg_cost: 'avg_cost', current_price: 'price', pnl_pct: 'pnl_pct'
  };
  const apiSort = SORT_MAP[sort] || 'weight';
  const { data, loading, error } = useHoldings(apiSort, order, assetClass === 'ALL' ? '' : assetClass);

  function handleSort(field) {
    if (sort === field) {
      setOrder(order === 'asc' ? 'desc' : 'asc');
    } else {
      setSort(field);
      setOrder('desc');
    }
  }

  function SortIcon({ field }) {
    if (sort !== field) return <ChevronsUpDown className="w-3 h-3 text-slate-300" />;
    return order === 'asc'
      ? <ChevronUp className="w-3 h-3 text-teal-600" />
      : <ChevronDown className="w-3 h-3 text-teal-600" />;
  }

  if (loading) return <Skeleton />;
  if (error) {
    return (
      <div className="bg-white rounded-xl border border-slate-200 p-5">
        <p className="text-red-600 text-sm">Failed to load holdings: {error}</p>
      </div>
    );
  }

  const holdings = data?.holdings || data || [];

  return (
    <div className="bg-white rounded-xl border border-slate-200 p-5">
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between mb-4 gap-3">
        <h2 className="text-xl font-semibold text-slate-800">Current Holdings</h2>
        <div className="flex items-center gap-2">
          <Filter className="w-4 h-4 text-slate-400" />
          <div className="flex flex-wrap gap-1">
            {ASSET_CLASSES.map((cls) => (
              <button
                key={cls}
                onClick={() => setAssetClass(cls)}
                className={`px-2.5 py-1 rounded-lg text-xs font-medium transition-colors ${
                  assetClass === cls
                    ? 'bg-teal-600 text-white'
                    : 'bg-slate-100 text-slate-600 hover:bg-slate-200'
                }`}
              >
                {cls}
              </button>
            ))}
          </div>
        </div>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="bg-slate-50 border-b border-slate-200">
              {[
                { key: 'asset_name', label: 'Name', align: 'left' },
                { key: 'asset_class', label: 'Class', align: 'left' },
                { key: 'quantity', label: 'Qty', align: 'right' },
                { key: 'avg_cost', label: 'Avg Cost', align: 'right' },
                { key: 'current_price', label: 'CMP', align: 'right' },
                { key: 'current_value', label: 'Value', align: 'right' },
                { key: 'unrealized_pnl', label: 'P&L', align: 'right' },
                { key: 'pnl_pct', label: 'P&L %', align: 'right' },
                { key: 'weight_pct', label: 'Weight', align: 'right' },
              ].map((col) => (
                <th
                  key={col.key}
                  onClick={() => handleSort(col.key)}
                  className={`px-3 py-2.5 text-xs font-semibold text-slate-400 uppercase tracking-wider whitespace-nowrap cursor-pointer select-none hover:text-slate-600 ${
                    col.align === 'right' ? 'text-right' : 'text-left'
                  }`}
                >
                  <div className={`flex items-center gap-1 ${col.align === 'right' ? 'justify-end' : ''}`}>
                    {col.label}
                    <SortIcon field={col.key} />
                  </div>
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {holdings.length === 0 ? (
              <tr>
                <td colSpan={9} className="px-4 py-12 text-center text-slate-400">
                  No holdings found.
                </td>
              </tr>
            ) : (
              holdings.map((h, idx) => (
                <tr key={h.symbol || idx} className="hover:bg-slate-50 transition-colors">
                  <td className="px-3 py-2.5">
                    <div>
                      <p className="font-medium text-slate-800 text-xs">{h.asset_name || h.symbol}</p>
                      {h.symbol && h.asset_name && (
                        <p className="text-xs text-slate-400">{h.symbol}</p>
                      )}
                    </div>
                  </td>
                  <td className="px-3 py-2.5">
                    <span
                      className="inline-block w-2 h-2 rounded-full mr-1.5"
                      style={{ backgroundColor: ASSET_CLASS_COLORS[h.asset_class] || '#94a3b8' }}
                    />
                    <span className="text-xs text-slate-600">{h.asset_class}</span>
                  </td>
                  <td className="px-3 py-2.5 text-right font-mono tabular-nums text-xs">
                    {h.quantity != null ? Number(h.quantity).toLocaleString('en-IN') : '--'}
                  </td>
                  <td className="px-3 py-2.5 text-right font-mono tabular-nums text-xs">
                    {formatINR(h.avg_cost)}
                  </td>
                  <td className="px-3 py-2.5 text-right font-mono tabular-nums text-xs">
                    {formatINR(h.current_price)}
                  </td>
                  <td className="px-3 py-2.5 text-right font-mono tabular-nums text-xs font-medium">
                    {formatINRShort(h.current_value)}
                  </td>
                  <td className={`px-3 py-2.5 text-right font-mono tabular-nums text-xs ${pnlColor(h.unrealized_pnl)}`}>
                    {formatINRShort(h.unrealized_pnl)}
                  </td>
                  <td className={`px-3 py-2.5 text-right font-mono tabular-nums text-xs ${pnlColor(h.pnl_pct)}`}>
                    {formatPct(h.pnl_pct)}
                  </td>
                  <td className="px-3 py-2.5 text-right font-mono tabular-nums text-xs">
                    {formatPct(h.weight_pct, 1)}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
