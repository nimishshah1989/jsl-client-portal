'use client';

import { useState } from 'react';
import { useTransactions } from '@/hooks/usePortfolio';
import { formatINR, formatDate, formatPct } from '@/lib/format';
import { TxnBadge } from '@/components/ui/Badge';
import { Pagination } from '@/components/ui/Table';
import { Filter, Search } from 'lucide-react';

function Skeleton() {
  return (
    <div className="bg-white rounded-xl border border-slate-200 p-5 animate-pulse">
      <div className="h-5 w-48 bg-slate-200 rounded mb-4" />
      <div className="space-y-3">
        {Array.from({ length: 8 }).map((_, i) => (
          <div key={i} className="h-10 bg-slate-100 rounded" />
        ))}
      </div>
    </div>
  );
}

const TXN_TYPES = ['ALL', 'BUY', 'SELL', 'BONUS', 'CORPUS_IN', 'SIP', 'DIVIDEND', 'REDEMPTION'];

export default function TransactionHistory() {
  const [page, setPage] = useState(1);
  const [filters, setFilters] = useState({ txn_type: '', asset_class: '' });
  const perPage = 25;

  const { data, loading, error } = useTransactions(page, perPage, filters);

  function handleTypeFilter(type) {
    setFilters((prev) => ({
      ...prev,
      txn_type: type === 'ALL' ? '' : type,
    }));
    setPage(1);
  }

  if (loading && !data) return <Skeleton />;
  if (error) {
    return (
      <div className="bg-white rounded-xl border border-slate-200 p-5">
        <p className="text-red-600 text-sm">Failed to load transactions: {error}</p>
      </div>
    );
  }

  const transactions = data?.transactions || data?.items || [];
  const totalPages = data?.total_pages || 1;
  const totalCount = data?.total || transactions.length;

  return (
    <div className="bg-white rounded-xl border border-slate-200 p-5">
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between mb-4 gap-3">
        <div>
          <h2 className="text-xl font-semibold text-slate-800">Transaction History</h2>
          <p className="text-xs text-slate-400 mt-0.5">{totalCount} transactions</p>
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          <Filter className="w-4 h-4 text-slate-400" />
          {TXN_TYPES.map((type) => (
            <button
              key={type}
              onClick={() => handleTypeFilter(type)}
              className={`px-2.5 py-1 rounded-lg text-xs font-medium transition-colors ${
                (filters.txn_type === type) || (type === 'ALL' && !filters.txn_type)
                  ? 'bg-teal-600 text-white'
                  : 'bg-slate-100 text-slate-600 hover:bg-slate-200'
              }`}
            >
              {type}
            </button>
          ))}
        </div>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="bg-slate-50 border-b border-slate-200">
              <th className="px-3 py-2.5 text-left text-xs font-semibold text-slate-400 uppercase tracking-wider">Date</th>
              <th className="px-3 py-2.5 text-left text-xs font-semibold text-slate-400 uppercase tracking-wider">Type</th>
              <th className="px-3 py-2.5 text-left text-xs font-semibold text-slate-400 uppercase tracking-wider">Script</th>
              <th className="px-3 py-2.5 text-left text-xs font-semibold text-slate-400 uppercase tracking-wider">Class</th>
              <th className="px-3 py-2.5 text-right text-xs font-semibold text-slate-400 uppercase tracking-wider">Qty</th>
              <th className="px-3 py-2.5 text-right text-xs font-semibold text-slate-400 uppercase tracking-wider">Price</th>
              <th className="px-3 py-2.5 text-right text-xs font-semibold text-slate-400 uppercase tracking-wider">Amount</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {transactions.length === 0 ? (
              <tr>
                <td colSpan={7} className="px-4 py-12 text-center text-slate-400">
                  No transactions found.
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
                      <p className="text-xs font-medium text-slate-800">{txn.asset_name || txn.symbol}</p>
                      {txn.symbol && txn.asset_name && (
                        <p className="text-xs text-slate-400">{txn.symbol}</p>
                      )}
                    </div>
                  </td>
                  <td className="px-3 py-2.5 text-xs text-slate-600">
                    {txn.asset_class}
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

      {totalPages > 1 && (
        <Pagination page={page} totalPages={totalPages} onPageChange={setPage} />
      )}
    </div>
  );
}
