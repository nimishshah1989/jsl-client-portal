'use client';

import { formatINR, formatINRShort } from '@/lib/format';
import { CheckCircle2, AlertTriangle, ChevronDown, ChevronRight, XCircle } from 'lucide-react';

const STATUS_CONFIG = {
  MATCH:         { label: 'Match',        color: 'bg-emerald-100 text-emerald-700', icon: CheckCircle2 },
  QTY_MISMATCH:  { label: 'Qty Mismatch', color: 'bg-amber-100 text-amber-700',    icon: AlertTriangle },
  COST_MISMATCH: { label: 'Cost Mismatch',color: 'bg-orange-100 text-orange-700',  icon: AlertTriangle },
  VALUE_MISMATCH:{ label: 'Value Mismatch',color: 'bg-yellow-100 text-yellow-700', icon: AlertTriangle },
  MISSING_IN_OURS:{ label: 'Missing',     color: 'bg-red-100 text-red-700',        icon: XCircle },
  EXTRA_IN_OURS: { label: 'Extra (EQ)',   color: 'bg-blue-100 text-blue-700',      icon: AlertTriangle },
  STRUCTURAL_ETF:{ label: 'ETF/MF ✓',    color: 'bg-slate-100 text-slate-500',    icon: null },
};

function StatusBadge({ status }) {
  const cfg = STATUS_CONFIG[status] || { label: status, color: 'bg-slate-100 text-slate-600' };
  const Icon = cfg.icon;
  return (
    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium ${cfg.color}`}>
      {Icon && <Icon className="w-3 h-3" />}
      {cfg.label}
    </span>
  );
}

function DiffCell({ value, threshold = 100 }) {
  if (value == null) return <td className="px-3 py-2 text-right font-mono text-slate-400">--</td>;
  const num = Number(value);
  const color = Math.abs(num) > threshold
    ? (num > 0 ? 'text-amber-600' : 'text-red-600')
    : 'text-slate-400';
  return (
    <td className={`px-3 py-2 text-right font-mono font-medium ${color}`}>
      {formatINR(num)}
    </td>
  );
}

/** Color for a diff relative to a base value. Green ≤1%, amber ≤5%, red >5% */
function diffColor(diff, base) {
  if (!base || base === 0) return 'text-slate-400';
  const pct = Math.abs(diff / base) * 100;
  if (pct <= 1) return 'text-slate-400';
  if (pct <= 5) return 'text-amber-600';
  return 'text-red-600';
}

export default function ReconciliationClientRow({ client, expanded, onToggle }) {
  const issues = client.qty_mismatch_count + client.cost_mismatch_count +
    client.value_mismatch_count + client.missing_in_ours_count + client.extra_in_ours_count;

  const navEquity  = client.nav_equity_component != null ? Number(client.nav_equity_component) : null;
  const holdingsTotal = Number(client.bo_holdings_total   || 0);
  const txnTotal      = Number(client.our_holdings_total  || 0);

  // NAV File equity component minus Transaction Data derived value
  const navVsTxn       = navEquity != null ? navEquity - txnTotal : null;
  // Holdings Data minus Transaction Data
  const holdingsVsTxn  = holdingsTotal - txnTotal;

  const sortedMatches = [...(client.matches || [])].sort((a, b) =>
    Math.abs(Number(b.value_diff || 0)) - Math.abs(Number(a.value_diff || 0))
  );

  return (
    <>
      <tr className="border-b border-slate-100 hover:bg-slate-50 cursor-pointer" onClick={onToggle}>
        <td className="px-3 py-3">
          {expanded
            ? <ChevronDown className="w-4 h-4 text-slate-400" />
            : <ChevronRight className="w-4 h-4 text-slate-400" />}
        </td>
        <td className="px-3 py-3 font-mono text-sm font-medium text-slate-800">{client.client_code}</td>
        <td className="px-3 py-3 text-sm text-slate-600 truncate max-w-[150px]" title={client.client_name}>
          {client.client_name || '--'}
        </td>

        {/* NAV File equity component */}
        <td className="px-3 py-3 text-sm font-mono text-right text-slate-600">
          {navEquity != null ? formatINRShort(navEquity) : '--'}
        </td>

        {/* Holdings Data (BO equity holding file) */}
        <td className="px-3 py-3 text-sm font-mono text-right text-slate-600">
          {formatINRShort(holdingsTotal)}
        </td>

        {/* Transaction Data (our derived) */}
        <td className="px-3 py-3 text-sm font-mono text-right text-slate-600">
          {formatINRShort(txnTotal)}
        </td>

        {/* NAV − Txn diff */}
        <td className={`px-3 py-3 text-sm font-mono text-right font-medium ${navVsTxn != null ? diffColor(navVsTxn, navEquity) : 'text-slate-400'}`}>
          {navVsTxn != null ? formatINRShort(navVsTxn) : '--'}
        </td>

        {/* Holdings − Txn diff */}
        <td className={`px-3 py-3 text-sm font-mono text-right font-medium ${diffColor(holdingsVsTxn, holdingsTotal)}`}>
          {formatINRShort(holdingsVsTxn)}
        </td>

        {/* Match % */}
        <td className="px-3 py-3 text-center">
          <span className={`font-mono text-sm font-medium ${client.match_pct === 100 ? 'text-emerald-600' : 'text-amber-600'}`}>
            {client.match_pct}%
          </span>
        </td>

        {/* Issues */}
        <td className="px-3 py-3 text-center">
          {issues > 0 ? (
            <span className="inline-flex items-center gap-1 text-sm text-red-600 font-medium">
              <AlertTriangle className="w-3.5 h-3.5" /> {issues}
            </span>
          ) : (
            <CheckCircle2 className="w-4 h-4 text-emerald-500 mx-auto" />
          )}
        </td>
      </tr>

      {expanded && (
        <tr>
          <td colSpan={10} className="px-0 py-0">
            <div className="bg-slate-50 border-y border-slate-200 overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="bg-slate-100">
                    <th className="px-3 py-2 text-left   text-xs font-semibold text-slate-500 uppercase">Symbol</th>
                    <th className="px-3 py-2 text-left   text-xs font-semibold text-slate-500 uppercase">Status</th>
                    <th className="px-3 py-2 text-right  text-xs font-semibold text-slate-500 uppercase">Holdings Qty</th>
                    <th className="px-3 py-2 text-right  text-xs font-semibold text-slate-500 uppercase">Txn Qty</th>
                    <th className="px-3 py-2 text-right  text-xs font-semibold text-slate-500 uppercase">Qty Diff</th>
                    <th className="px-3 py-2 text-right  text-xs font-semibold text-slate-500 uppercase">Mkt Price</th>
                    <th className="px-3 py-2 text-right  text-xs font-semibold text-slate-500 uppercase">Holdings Avg Cost</th>
                    <th className="px-3 py-2 text-right  text-xs font-semibold text-slate-500 uppercase">Txn Avg Cost</th>
                    <th className="px-3 py-2 text-right  text-xs font-semibold text-slate-500 uppercase">Cost Diff</th>
                    <th className="px-3 py-2 text-right  text-xs font-semibold text-slate-500 uppercase">Holdings Value</th>
                    <th className="px-3 py-2 text-right  text-xs font-semibold text-slate-500 uppercase">Txn Value</th>
                    <th className="px-3 py-2 text-right  text-xs font-semibold text-slate-500 uppercase bg-slate-200">Value Diff</th>
                  </tr>
                </thead>
                <tbody>
                  {sortedMatches.map((m, i) => (
                    <tr key={i} className={`border-b border-slate-100 ${
                      m.status === 'STRUCTURAL_ETF' ? 'opacity-60' :
                      m.status !== 'MATCH' ? 'bg-amber-50/50' : ''
                    }`}>
                      <td className="px-3 py-2 font-mono font-medium text-slate-800">{m.symbol}</td>
                      <td className="px-3 py-2"><StatusBadge status={m.status} /></td>
                      <td className="px-3 py-2 text-right font-mono">{m.bo_quantity ?? '--'}</td>
                      <td className="px-3 py-2 text-right font-mono">{m.our_quantity ?? '--'}</td>
                      <td className={`px-3 py-2 text-right font-mono ${m.qty_diff && Number(m.qty_diff) !== 0 ? 'text-red-600 font-medium' : 'text-slate-400'}`}>
                        {m.qty_diff != null ? Number(m.qty_diff) : '--'}
                      </td>
                      <td className="px-3 py-2 text-right font-mono text-slate-600">
                        {m.bo_market_price != null ? formatINR(Number(m.bo_market_price), 2) : '--'}
                      </td>
                      <td className="px-3 py-2 text-right font-mono">
                        {m.bo_avg_cost != null ? formatINR(Number(m.bo_avg_cost), 2) : '--'}
                      </td>
                      <td className="px-3 py-2 text-right font-mono">
                        {m.our_avg_cost != null ? formatINR(Number(m.our_avg_cost), 2) : '--'}
                      </td>
                      <td className={`px-3 py-2 text-right font-mono ${m.cost_diff && Math.abs(Number(m.cost_diff)) > 0.02 ? 'text-red-600 font-medium' : 'text-slate-400'}`}>
                        {m.cost_diff != null ? formatINR(Number(m.cost_diff), 4) : '--'}
                      </td>
                      <td className="px-3 py-2 text-right font-mono">
                        {m.bo_market_value != null ? formatINR(Number(m.bo_market_value)) : '--'}
                      </td>
                      <td className="px-3 py-2 text-right font-mono">
                        {m.our_market_value != null ? formatINR(Number(m.our_market_value)) : '--'}
                      </td>
                      <DiffCell value={m.value_diff} />
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </td>
        </tr>
      )}
    </>
  );
}
