'use client';

import { useState } from 'react';
import { useHoldings } from '@/hooks/usePortfolio';
import { formatINR, formatINRShort, formatPct, formatDate, pnlColor } from '@/lib/format';
import { SECTOR_COLORS } from '@/lib/constants';
import { ChevronUp, ChevronDown, ChevronsUpDown } from 'lucide-react';

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

// Filter pills removed — sector-only view, no asset_class filtering

export default function HoldingsTable() {
  const [sort, setSort] = useState('weight_pct');
  const [order, setOrder] = useState('desc');
  // Map frontend field names to backend-accepted sort keys
  const SORT_MAP = {
    weight_pct: 'weight', unrealized_pnl: 'pnl', current_value: 'value',
    symbol: 'name', asset_name: 'name', sector: 'name',
    quantity: 'quantity', avg_cost: 'avg_cost', current_price: 'price', pnl_pct: 'pnl_pct'
  };
  const apiSort = SORT_MAP[sort] || 'weight';
  const { data, loading, error } = useHoldings(apiSort, order, '');

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

  const holdings = data?.holdings || (Array.isArray(data) ? data : []) || [];
  // Cash is part of the total portfolio — shown as its own rows so weights
  // (equity + cash) sum to ~100%.
  const cash = data?.cash || [];
  const asOfDate = data?.as_of_date || null;

  // Equity subtotals
  const totals = holdings.reduce(
    (acc, h) => ({
      current_value: acc.current_value + (Number(h.current_value) || 0),
      unrealized_pnl: acc.unrealized_pnl + (Number(h.unrealized_pnl) || 0),
      weight_pct: acc.weight_pct + (Number(h.weight_pct) || 0),
    }),
    { current_value: 0, unrealized_pnl: 0, weight_pct: 0 }
  );
  // Cash subtotals
  const cashTotals = cash.reduce(
    (acc, c) => ({
      value: acc.value + (Number(c.value) || 0),
      weight_pct: acc.weight_pct + (Number(c.weight_pct) || 0),
    }),
    { value: 0, weight_pct: 0 }
  );
  // Grand total — prefer the server's total_value, fall back to the sum.
  const grandValue =
    data?.total_value != null
      ? Number(data.total_value)
      : totals.current_value + cashTotals.value;
  const grandWeight = totals.weight_pct + cashTotals.weight_pct;
  const hasRows = holdings.length > 0 || cash.length > 0;

  return (
    <div className="bg-white rounded-xl border border-slate-200 p-3 sm:p-5 overflow-hidden">
      <div className="mb-4">
        <h2 className="text-lg sm:text-xl font-semibold text-slate-800">Current Holdings</h2>
        <p className="text-xs text-slate-400 mt-0.5">
          Weights are on total portfolio value (incl. cash)
          {asOfDate ? ` · as of ${formatDate(asOfDate)}` : ''}
        </p>
      </div>

      <div className="overflow-x-auto" style={{ WebkitOverflowScrolling: 'touch' }}>
        <table className="min-w-[700px] w-full text-sm">
          <thead>
            <tr className="bg-slate-50 border-b border-slate-200">
              {[
                { key: 'asset_name', label: 'Name', align: 'left' },
                { key: 'sector', label: 'Sector', align: 'left' },
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
            {!hasRows ? (
              <tr>
                <td colSpan={9} className="px-4 py-12 text-center text-slate-400">
                  No holdings found.
                </td>
              </tr>
            ) : (
              <>
              {holdings.map((h, idx) => (
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
                      style={{ backgroundColor: SECTOR_COLORS[h.sector] || '#94a3b8' }}
                    />
                    <span className="text-xs text-slate-600">{h.sector || 'Other'}</span>
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
              ))}
              {cash.map((c) => (
                <tr key={c.label} className="bg-amber-50/40 hover:bg-amber-50 transition-colors">
                  <td className="px-3 py-2.5" colSpan={2}>
                    <div className="flex items-center gap-1.5">
                      <span className="inline-block w-2 h-2 rounded-full" style={{ backgroundColor: '#d97706' }} />
                      <span className="font-medium text-slate-700 text-xs">{c.label}</span>
                    </div>
                  </td>
                  <td className="px-3 py-2.5 text-right text-xs text-slate-300">—</td>
                  <td className="px-3 py-2.5 text-right text-xs text-slate-300">—</td>
                  <td className="px-3 py-2.5 text-right text-xs text-slate-300">—</td>
                  <td className="px-3 py-2.5 text-right font-mono tabular-nums text-xs font-medium">
                    {formatINRShort(c.value)}
                  </td>
                  <td className="px-3 py-2.5 text-right text-xs text-slate-300">—</td>
                  <td className="px-3 py-2.5 text-right text-xs text-slate-300">—</td>
                  <td className="px-3 py-2.5 text-right font-mono tabular-nums text-xs">
                    {formatPct(c.weight_pct, 1)}
                  </td>
                </tr>
              ))}
              </>
            )}
          </tbody>
          {hasRows && (
            <tfoot>
              <tr className="bg-slate-50 border-t-2 border-slate-300">
                <td colSpan={5} className="px-3 py-2.5 text-xs font-semibold text-slate-700">
                  Total Portfolio ({holdings.length} holdings{cash.length > 0 ? ' + cash' : ''})
                </td>
                <td className="px-3 py-2.5 text-right font-mono tabular-nums text-xs font-semibold text-slate-800">
                  {formatINRShort(grandValue)}
                </td>
                <td className={`px-3 py-2.5 text-right font-mono tabular-nums text-xs font-semibold ${pnlColor(totals.unrealized_pnl)}`}>
                  {formatINRShort(totals.unrealized_pnl)}
                </td>
                <td className="px-3 py-2.5" />
                <td className="px-3 py-2.5 text-right font-mono tabular-nums text-xs font-semibold text-slate-700">
                  {formatPct(grandWeight, 1)}
                </td>
              </tr>
            </tfoot>
          )}
        </table>
      </div>
    </div>
  );
}
