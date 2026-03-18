'use client';

import { useState, useCallback, useEffect } from 'react';
import { apiGet } from '@/lib/api';
import { formatINR, formatDate } from '@/lib/format';
import { TxnBadge } from '@/components/ui/Badge';
import { Pagination } from '@/components/ui/Table';
import { ChevronDown, ChevronUp, Filter, Calendar } from 'lucide-react';

const RANGE_PRESETS = [
  { label: '1W', days: 7 },
  { label: '1M', days: 30 },
  { label: '3M', days: 91 },
  { label: '6M', days: 182 },
  { label: '1Y', days: 365 },
  { label: 'All', days: null },
];

const TXN_TYPES = ['ALL', 'BUY', 'SELL', 'BONUS', 'CORPUS_IN', 'SIP', 'DIVIDEND', 'REDEMPTION'];

function toISODate(date) {
  return date.toISOString().split('T')[0];
}

function computeDateRange(days) {
  const to = new Date();
  if (days === null) return { date_from: '', date_to: '' };
  const from = new Date();
  from.setDate(from.getDate() - days);
  return { date_from: toISODate(from), date_to: toISODate(to) };
}

function Skeleton() {
  return (
    <div className="animate-pulse space-y-3 mt-4">
      {Array.from({ length: 6 }).map((_, i) => (
        <div key={i} className="h-10 bg-slate-100 rounded" />
      ))}
    </div>
  );
}

export default function TransactionHistory() {
  const [expanded, setExpanded] = useState(false);
  const [activePreset, setActivePreset] = useState('1M');
  const [customFrom, setCustomFrom] = useState('');
  const [customTo, setCustomTo] = useState('');
  const [txnType, setTxnType] = useState('');
  const [page, setPage] = useState(1);
  const perPage = 25;

  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [hasFetched, setHasFetched] = useState(false);

  const fetchTransactions = useCallback(async (dateFrom, dateTo, type, pg) => {
    setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams({
        page: String(pg),
        per_page: String(perPage),
      });
      if (dateFrom) params.set('date_from', dateFrom);
      if (dateTo) params.set('date_to', dateTo);
      if (type) params.set('txn_type', type);
      const result = await apiGet(`/portfolio/transactions?${params.toString()}`);
      setData(result);
      setHasFetched(true);
    } catch (err) {
      setError(err.message || 'Failed to load transactions');
    } finally {
      setLoading(false);
    }
  }, [perPage]);

  // Fetch when expanded for the first time (default 1M)
  useEffect(() => {
    if (expanded && !hasFetched) {
      const { date_from, date_to } = computeDateRange(30);
      fetchTransactions(date_from, date_to, txnType, 1);
    }
  }, [expanded, hasFetched, fetchTransactions, txnType]);

  function handlePresetClick(preset) {
    setActivePreset(preset.label);
    setCustomFrom('');
    setCustomTo('');
    setPage(1);
    const { date_from, date_to } = computeDateRange(preset.days);
    fetchTransactions(date_from, date_to, txnType, 1);
  }

  function handleCustomApply() {
    if (!customFrom || !customTo) return;
    setActivePreset(null);
    setPage(1);
    fetchTransactions(customFrom, customTo, txnType, 1);
  }

  function handleTypeFilter(type) {
    const newType = type === 'ALL' ? '' : type;
    setTxnType(newType);
    setPage(1);

    let dateFrom = '';
    let dateTo = '';
    if (activePreset) {
      const preset = RANGE_PRESETS.find((p) => p.label === activePreset);
      if (preset) {
        const range = computeDateRange(preset.days);
        dateFrom = range.date_from;
        dateTo = range.date_to;
      }
    } else {
      dateFrom = customFrom;
      dateTo = customTo;
    }
    fetchTransactions(dateFrom, dateTo, newType, 1);
  }

  function handlePageChange(newPage) {
    setPage(newPage);
    let dateFrom = '';
    let dateTo = '';
    if (activePreset) {
      const preset = RANGE_PRESETS.find((p) => p.label === activePreset);
      if (preset) {
        const range = computeDateRange(preset.days);
        dateFrom = range.date_from;
        dateTo = range.date_to;
      }
    } else {
      dateFrom = customFrom;
      dateTo = customTo;
    }
    fetchTransactions(dateFrom, dateTo, txnType, newPage);
  }

  const transactions = data?.transactions || data?.items || [];
  const totalPages = data?.total_pages || 1;
  const totalCount = data?.total || transactions.length;

  return (
    <div className="bg-white rounded-xl border border-slate-200 overflow-hidden">
      {/* Collapsed header — always visible */}
      <button
        onClick={() => setExpanded((prev) => !prev)}
        className="w-full flex items-center justify-between p-5 text-left"
      >
        <div>
          <h2 className="text-xl font-semibold text-slate-800">Transaction History</h2>
          {!expanded && (
            <p className="text-xs text-slate-400 mt-0.5">
              Click to view transactions
            </p>
          )}
          {expanded && hasFetched && (
            <p className="text-xs text-slate-400 mt-0.5">
              {totalCount} transaction{totalCount !== 1 ? 's' : ''} found
            </p>
          )}
        </div>
        <div className="flex items-center gap-2">
          {!expanded && (
            <span className="text-xs font-medium text-teal-600 hidden sm:inline">
              View Transactions
            </span>
          )}
          {expanded ? (
            <ChevronUp className="w-5 h-5 text-slate-400" />
          ) : (
            <ChevronDown className="w-5 h-5 text-slate-400" />
          )}
        </div>
      </button>

      {/* Expanded content */}
      {expanded && (
        <div className="px-5 pb-5 space-y-4">
          {/* Time range presets */}
          <div className="flex flex-col gap-3">
            <div className="flex flex-wrap items-center gap-2">
              <Calendar className="w-4 h-4 text-slate-400 flex-shrink-0" />
              {RANGE_PRESETS.map((preset) => (
                <button
                  key={preset.label}
                  onClick={() => handlePresetClick(preset)}
                  className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${
                    activePreset === preset.label
                      ? 'bg-teal-600 text-white'
                      : 'bg-slate-100 text-slate-600 hover:bg-slate-200'
                  }`}
                >
                  {preset.label}
                </button>
              ))}
            </div>

            {/* Custom date range */}
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-xs text-slate-500 flex-shrink-0">Custom:</span>
              <input
                type="date"
                value={customFrom}
                onChange={(e) => setCustomFrom(e.target.value)}
                className="px-2.5 py-1.5 text-xs border border-slate-200 rounded-lg bg-white text-slate-700 focus:outline-none focus:ring-2 focus:ring-teal-500 focus:border-transparent"
              />
              <span className="text-xs text-slate-400">to</span>
              <input
                type="date"
                value={customTo}
                onChange={(e) => setCustomTo(e.target.value)}
                className="px-2.5 py-1.5 text-xs border border-slate-200 rounded-lg bg-white text-slate-700 focus:outline-none focus:ring-2 focus:ring-teal-500 focus:border-transparent"
              />
              <button
                onClick={handleCustomApply}
                disabled={!customFrom || !customTo}
                className="px-3 py-1.5 rounded-lg text-xs font-medium bg-slate-800 text-white hover:bg-slate-700 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
              >
                Apply
              </button>
            </div>
          </div>

          {/* Transaction type filter */}
          <div className="flex items-center gap-2 flex-wrap">
            <Filter className="w-4 h-4 text-slate-400 flex-shrink-0" />
            {TXN_TYPES.map((type) => (
              <button
                key={type}
                onClick={() => handleTypeFilter(type)}
                className={`px-2.5 py-1 rounded-lg text-xs font-medium transition-colors ${
                  (txnType === type) || (type === 'ALL' && !txnType)
                    ? 'bg-teal-600 text-white'
                    : 'bg-slate-100 text-slate-600 hover:bg-slate-200'
                }`}
              >
                {type}
              </button>
            ))}
          </div>

          {/* Loading state */}
          {loading && <Skeleton />}

          {/* Error state */}
          {error && !loading && (
            <p className="text-red-600 text-sm py-4">Failed to load transactions: {error}</p>
          )}

          {/* Transaction table */}
          {!loading && !error && hasFetched && (
            <>
              <div className="overflow-x-auto -mx-5">
                <div className="min-w-[600px] px-5">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="bg-slate-50 border-b border-slate-200">
                        <th className="px-3 py-2.5 text-left text-xs font-semibold text-slate-400 uppercase tracking-wider">Date</th>
                        <th className="px-3 py-2.5 text-left text-xs font-semibold text-slate-400 uppercase tracking-wider">Type</th>
                        <th className="px-3 py-2.5 text-left text-xs font-semibold text-slate-400 uppercase tracking-wider">Symbol</th>
                        <th className="px-3 py-2.5 text-right text-xs font-semibold text-slate-400 uppercase tracking-wider">Qty</th>
                        <th className="px-3 py-2.5 text-right text-xs font-semibold text-slate-400 uppercase tracking-wider">Price</th>
                        <th className="px-3 py-2.5 text-right text-xs font-semibold text-slate-400 uppercase tracking-wider">Amount</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-100">
                      {transactions.length === 0 ? (
                        <tr>
                          <td colSpan={6} className="px-4 py-12 text-center text-slate-400">
                            No transactions found for this period.
                          </td>
                        </tr>
                      ) : (
                        transactions.map((txn, idx) => (
                          <tr key={txn.id || idx} className="hover:bg-slate-50 transition-colors">
                            <td className="px-3 py-2.5 text-xs text-slate-600 whitespace-nowrap">
                              {formatDate(txn.txn_date)}
                            </td>
                            <td className="px-3 py-2.5">
                              <TxnBadge type={txn.txn_type} />
                            </td>
                            <td className="px-3 py-2.5">
                              <div>
                                <p className="text-xs font-medium text-slate-800">
                                  {txn.asset_name || txn.symbol}
                                </p>
                                {txn.symbol && txn.asset_name && (
                                  <p className="text-xs text-slate-400">{txn.symbol}</p>
                                )}
                              </div>
                            </td>
                            <td className="px-3 py-2.5 text-right font-mono tabular-nums text-xs">
                              {txn.quantity != null ? Number(txn.quantity).toLocaleString('en-IN') : '--'}
                            </td>
                            <td className="px-3 py-2.5 text-right font-mono tabular-nums text-xs">
                              {formatINR(txn.price)}
                            </td>
                            <td className="px-3 py-2.5 text-right font-mono tabular-nums text-xs font-medium">
                              {formatINR(txn.amount)}
                            </td>
                          </tr>
                        ))
                      )}
                    </tbody>
                  </table>
                </div>
              </div>

              {totalPages > 1 && (
                <Pagination page={page} totalPages={totalPages} onPageChange={handlePageChange} />
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
}
