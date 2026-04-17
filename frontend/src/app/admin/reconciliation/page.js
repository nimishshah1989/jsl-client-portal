'use client';

import { useState, useCallback, useMemo } from 'react';
import { apiFetch } from '@/lib/api';
import { formatINRShort } from '@/lib/format';
import { Download, Search, Filter } from 'lucide-react';
import ReconciliationClientRow from '@/components/admin/ReconciliationClientRow';

/** Single metric card — label, big value, small subtitle */
function MetricCard({ label, value, sub, color = 'text-slate-800' }) {
  return (
    <div className="bg-slate-50 rounded-lg p-3">
      <p className="text-xs text-slate-500">{label}</p>
      <p className={`text-2xl font-bold font-mono mt-0.5 ${color}`}>{value}</p>
      {sub && <p className="text-xs text-slate-400 mt-0.5">{sub}</p>}
    </div>
  );
}

/** Source vs Target comparison block with 2 or 3 metrics */
function ComparisonBlock({ source, target, desc, metrics }) {
  return (
    <div className="bg-white rounded-xl border border-slate-200 p-5">
      <div className="mb-4">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-xs font-bold text-teal-700 bg-teal-50 border border-teal-200 px-2.5 py-0.5 rounded-full">
            {source}
          </span>
          <span className="text-xs text-slate-400 font-medium">vs</span>
          <span className="text-xs font-bold text-slate-600 bg-slate-100 border border-slate-200 px-2.5 py-0.5 rounded-full">
            {target}
          </span>
        </div>
        <p className="text-xs text-slate-400 mt-2">{desc}</p>
      </div>
      <div className={`grid gap-3 ${metrics.length === 2 ? 'grid-cols-2' : 'grid-cols-3'}`}>
        {metrics.map((m, i) => (
          <MetricCard key={i} label={m.label} value={m.value} sub={m.sub} color={m.color} />
        ))}
      </div>
    </div>
  );
}

function accColor(pct) {
  if (pct >= 95) return 'text-emerald-600';
  if (pct >= 80) return 'text-amber-600';
  return 'text-red-600';
}

function diffAmtColor(diff, base) {
  if (!base) return 'text-slate-800';
  const pct = Math.abs(diff / base) * 100;
  if (pct <= 1) return 'text-emerald-600';
  if (pct <= 5) return 'text-amber-600';
  return 'text-red-600';
}

export default function ReconciliationPage() {
  const [data, setData]               = useState(null);
  const [initialLoading, setInitialLoading] = useState(true);
  const [error, setError]             = useState(null);
  const [expandedClients, setExpandedClients] = useState(new Set());
  const [searchTerm, setSearchTerm]   = useState('');
  const [statusFilter, setStatusFilter] = useState('ALL');

  useState(() => {
    (async () => {
      try {
        const result = await apiFetch('/admin/reconciliation/summary');
        setData(result);
      } catch { /* No saved data — fine */ } finally {
        setInitialLoading(false);
      }
    })();
  });

  const handleExport = useCallback(async () => {
    try {
      const response = await fetch('/api/admin/reconciliation/export', { credentials: 'include' });
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url; a.download = 'reconciliation_mismatches.csv'; a.click();
      URL.revokeObjectURL(url);
    } catch { setError('Export failed'); }
  }, []);

  const toggleClient = useCallback((code) => {
    setExpandedClients(prev => {
      const next = new Set(prev);
      next.has(code) ? next.delete(code) : next.add(code);
      return next;
    });
  }, []);

  const filteredClients = useMemo(() => {
    if (!data?.clients) return [];
    return data.clients.filter(c => {
      const matchesSearch = !searchTerm ||
        c.client_code.toLowerCase().includes(searchTerm.toLowerCase()) ||
        (c.client_name || '').toLowerCase().includes(searchTerm.toLowerCase()) ||
        c.family_group.toLowerCase().includes(searchTerm.toLowerCase());
      const matchesFilter = statusFilter === 'ALL' ||
        (statusFilter === 'ISSUES_ONLY' && c.has_issues) ||
        (statusFilter === 'MATCH_ONLY' && !c.has_issues);
      return matchesSearch && matchesFilter;
    });
  }, [data, searchTerm, statusFilter]);

  // ── Derived metrics for comparison blocks ────────────────────────────────

  const metrics = useMemo(() => {
    if (!data) return null;

    const navEqTotal  = Number(data.total_nav_equity_value  || 0);
    const ourEqTotal  = Number(data.total_our_holdings_value || 0);
    const navVsTxnDiff = navEqTotal - ourEqTotal;
    const navAmtAccPct = navEqTotal > 0
      ? Math.max(0, (1 - Math.abs(navVsTxnDiff) / navEqTotal) * 100) : 0;

    // NAV client accuracy: % clients whose nav_equity is within ±5% of txn-derived
    const navClientsArr = (data.clients || []).filter(
      c => c.nav_equity_component != null && Number(c.nav_equity_component) > 0
    );
    const navClientsIn5pct = navClientsArr.filter(c => {
      const eq = Number(c.nav_equity_component);
      return Math.abs(eq - Number(c.our_holdings_total || 0)) / eq <= 0.05;
    }).length;
    const navClientAccPct = navClientsArr.length > 0
      ? (navClientsIn5pct / navClientsArr.length * 100) : 0;

    const boTotal    = Number(data.total_bo_holdings_value || 0);
    const boVsOurs   = Number(data.total_bo_vs_ours_diff   || 0);
    const hldAmtAccPct = boTotal > 0
      ? Math.max(0, (1 - Math.abs(boVsOurs) / boTotal) * 100) : 0;

    const totalPositions   = data.total_holdings_bo   || 0;
    const matchedPositions = data.total_holdings_matched || 0;
    const hldPosAccPct = totalPositions > 0
      ? (matchedPositions / totalPositions * 100) : 0;

    const hldClientAccPct   = data.client_match_pct     || 0;
    const hldClientsMatched = data.clients_fully_matched || 0;
    const totalClients      = data.total_clients_bo      || 0;

    return {
      nav: {
        clientAccPct: navClientAccPct,
        clientsIn5:   navClientsIn5pct,
        clientsTotal: navClientsArr.length,
        amtAccPct:    navAmtAccPct,
        diff:         navVsTxnDiff,
        navEqTotal,
      },
      hld: {
        clientAccPct:   hldClientAccPct,
        clientsMatched: hldClientsMatched,
        clientsTotal:   totalClients,
        amtAccPct:      hldAmtAccPct,
        diff:           boVsOurs,
        boTotal,
        posAccPct:      hldPosAccPct,
        matched:        matchedPositions,
        total:          totalPositions,
      },
    };
  }, [data]);

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-semibold text-slate-800">Holdings Reconciliation</h2>
          <p className="text-sm text-slate-500 mt-1">
            NAV File · Holdings Data · Transaction Data — three-way accuracy check
          </p>
        </div>
        {data && (
          <div className="flex items-center gap-2">
            {data.total_cost_mismatches > 0 && (
              <button
                onClick={async () => {
                  if (!confirm(`Sync avg cost for ${data.total_cost_mismatches} cost mismatches from Holdings Data?`)) return;
                  try {
                    const r = await apiFetch('/admin/reconciliation/sync-costs', { method: 'POST' });
                    alert(`Synced ${r.updated} holdings. Re-upload Holdings Data to verify.`);
                  } catch (err) { setError(err.message || 'Sync failed'); }
                }}
                className="flex items-center gap-2 px-4 py-2 text-sm font-medium text-teal-700 bg-teal-50 border border-teal-200 rounded-lg hover:bg-teal-100"
              >
                Sync Costs ({data.total_cost_mismatches})
              </button>
            )}
            <button onClick={handleExport} className="flex items-center gap-2 px-4 py-2 text-sm font-medium text-slate-600 bg-white border border-slate-200 rounded-lg hover:bg-slate-50">
              <Download className="w-4 h-4" /> Export
            </button>
          </div>
        )}
      </div>

      {error && <div className="bg-red-50 border border-red-200 rounded-lg p-4 text-sm text-red-700">{error}</div>}

      {data && metrics && (
        <>
          {/* ── Two comparison blocks ─────────────────────────────────────── */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            <ComparisonBlock
              source="NAV File"
              target="Transaction Data"
              desc="How closely our transaction-derived equity holdings match the NAV file's equity component"
              metrics={[
                {
                  label: 'Client Accuracy',
                  value: `${metrics.nav.clientAccPct.toFixed(1)}%`,
                  sub: `${metrics.nav.clientsIn5} / ${metrics.nav.clientsTotal} clients within ±5%`,
                  color: accColor(metrics.nav.clientAccPct),
                },
                {
                  label: 'Amount Accuracy',
                  value: `${metrics.nav.amtAccPct.toFixed(1)}%`,
                  sub: `${formatINRShort(Math.abs(metrics.nav.diff))} difference`,
                  color: accColor(metrics.nav.amtAccPct),
                },
              ]}
            />
            <ComparisonBlock
              source="Holdings Data"
              target="Transaction Data"
              desc="Position-by-position match between the equity holding report and our transaction-derived holdings"
              metrics={[
                {
                  label: 'Client Accuracy',
                  value: `${metrics.hld.clientAccPct.toFixed(1)}%`,
                  sub: `${metrics.hld.clientsMatched} / ${metrics.hld.clientsTotal} clients fully clean`,
                  color: accColor(metrics.hld.clientAccPct),
                },
                {
                  label: 'Amount Accuracy',
                  value: `${metrics.hld.amtAccPct.toFixed(1)}%`,
                  sub: `${formatINRShort(Math.abs(metrics.hld.diff))} difference`,
                  color: accColor(metrics.hld.amtAccPct),
                },
                {
                  label: 'Holdings Accuracy',
                  value: `${metrics.hld.posAccPct.toFixed(1)}%`,
                  sub: `${metrics.hld.matched} / ${metrics.hld.total} positions match`,
                  color: accColor(metrics.hld.posAccPct),
                },
              ]}
            />
          </div>

          {/* ── Reference: NAV breakdown + issue counts ───────────────────── */}
          <div className="bg-white rounded-xl border border-slate-200 p-4">
            <p className="text-xs font-semibold text-slate-500 uppercase tracking-wider mb-3">
              NAV Breakdown &amp; Issue Counts
            </p>
            <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-8 gap-2 text-xs">
              {[
                { label: 'NAV Equity',    value: formatINRShort(Number(data.total_nav_equity_value || 0)) },
                { label: 'NAV ETF',       value: formatINRShort(Number(data.total_etf_value || 0)) },
                { label: 'NAV Cash',      value: formatINRShort(Number(data.total_cash_value || 0)) },
                { label: 'NAV Total',     value: formatINRShort(Number(data.total_nav_value || 0)) },
                {
                  label: 'Qty Mismatches',
                  value: data.total_qty_mismatches,
                  color: data.total_qty_mismatches > 0 ? 'text-amber-600' : 'text-emerald-600',
                },
                {
                  label: 'Cost Mismatches',
                  value: data.total_cost_mismatches,
                  color: data.total_cost_mismatches > 0 ? 'text-orange-600' : 'text-emerald-600',
                },
                {
                  label: 'Missing in Txn',
                  value: data.total_missing_in_ours,
                  color: data.total_missing_in_ours > 0 ? 'text-red-600' : 'text-emerald-600',
                },
                { label: 'ETF/MF (excl.)', value: data.total_structural_etf || 0, color: 'text-slate-400' },
              ].map((item, i) => (
                <div key={i} className="bg-slate-50 rounded-lg px-3 py-2">
                  <p className="text-slate-400">{item.label}</p>
                  <p className={`font-mono font-semibold mt-0.5 ${item.color || 'text-slate-700'}`}>
                    {item.value}
                  </p>
                </div>
              ))}
            </div>
            <div className="flex items-center gap-4 mt-3 text-xs text-slate-400">
              {data.market_date && <span>Holdings Data as of: <span className="font-medium text-slate-600">{data.market_date}</span></span>}
              {data.run_at && <span>Reconciled: <span className="font-medium text-slate-600">{new Date(data.run_at).toLocaleString('en-IN')}</span></span>}
              <span>Transaction Data value = our qty × Holdings Data market price</span>
            </div>
          </div>

          {/* ── Commentary ───────────────────────────────────────────────── */}
          {data.commentary?.length > 0 && (
            <div className="bg-white rounded-xl border border-slate-200 p-5 space-y-3">
              <h3 className="text-sm font-semibold text-slate-700 uppercase tracking-wider">Insights</h3>
              {data.commentary.map((c, i) => {
                const styles = { critical: 'border-l-red-500 bg-red-50', high: 'border-l-amber-500 bg-amber-50', medium: 'border-l-yellow-400 bg-yellow-50', good: 'border-l-emerald-500 bg-emerald-50', info: 'border-l-blue-400 bg-blue-50' };
                const text   = { critical: 'text-red-800', high: 'text-amber-800', medium: 'text-yellow-800', good: 'text-emerald-800', info: 'text-blue-800' };
                return (
                  <div key={i} className={`border-l-4 rounded-r-lg p-3 ${styles[c.severity] || 'bg-slate-50 border-l-slate-300'}`}>
                    <div className="flex items-start justify-between gap-2">
                      <p className={`text-sm font-medium ${text[c.severity] || 'text-slate-800'}`}>{c.title}</p>
                      {c.affected_clients > 0 && <span className="text-xs text-slate-500 whitespace-nowrap">{c.affected_clients} clients</span>}
                    </div>
                    <p className="text-xs text-slate-600 mt-1">{c.detail}</p>
                  </div>
                );
              })}
            </div>
          )}

          {/* ── Filters ──────────────────────────────────────────────────── */}
          <div className="flex items-center gap-4">
            <div className="relative flex-1 max-w-xs">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />
              <input type="text" placeholder="Search client code, name, or group..."
                value={searchTerm} onChange={e => setSearchTerm(e.target.value)}
                className="w-full pl-9 pr-4 py-2 text-sm border border-slate-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-teal-500 focus:border-transparent" />
            </div>
            <div className="flex items-center gap-2">
              <Filter className="w-4 h-4 text-slate-400" />
              {['ALL', 'ISSUES_ONLY', 'MATCH_ONLY'].map(f => (
                <button key={f} onClick={() => setStatusFilter(f)}
                  className={`px-3 py-1.5 text-xs font-medium rounded-lg transition-colors ${statusFilter === f ? 'bg-teal-100 text-teal-700' : 'bg-slate-100 text-slate-500 hover:bg-slate-200'}`}>
                  {f === 'ALL' ? 'All' : f === 'ISSUES_ONLY' ? 'Issues Only' : 'Clean Only'}
                </button>
              ))}
            </div>
            <span className="text-xs text-slate-400">{filteredClients.length} of {data.clients.length} clients</span>
          </div>

          {/* ── Client Table ──────────────────────────────────────────────── */}
          <div className="bg-white rounded-xl border border-slate-200 overflow-hidden">
            <table className="w-full">
              <thead>
                <tr className="bg-slate-50 border-b border-slate-200">
                  <th className="px-3 py-3 w-8" />
                  <th className="px-3 py-3 text-left  text-xs font-semibold text-slate-500 uppercase tracking-wider">Code</th>
                  <th className="px-3 py-3 text-left  text-xs font-semibold text-slate-500 uppercase tracking-wider">Name</th>
                  <th className="px-3 py-3 text-right text-xs font-semibold text-slate-500 uppercase tracking-wider">NAV File (equity)</th>
                  <th className="px-3 py-3 text-right text-xs font-semibold text-slate-500 uppercase tracking-wider">Holdings Data</th>
                  <th className="px-3 py-3 text-right text-xs font-semibold text-slate-500 uppercase tracking-wider">Transaction Data</th>
                  <th className="px-3 py-3 text-right text-xs font-semibold text-teal-600   uppercase tracking-wider">NAV − Txn</th>
                  <th className="px-3 py-3 text-right text-xs font-semibold text-teal-600   uppercase tracking-wider">Holdings − Txn</th>
                  <th className="px-3 py-3 text-center text-xs font-semibold text-slate-500 uppercase tracking-wider">Match %</th>
                  <th className="px-3 py-3 text-center text-xs font-semibold text-slate-500 uppercase tracking-wider">Issues</th>
                </tr>
              </thead>
              <tbody>
                {filteredClients.map(client => (
                  <ReconciliationClientRow
                    key={client.client_code}
                    client={client}
                    expanded={expandedClients.has(client.client_code)}
                    onToggle={() => toggleClient(client.client_code)}
                  />
                ))}
              </tbody>
            </table>
            {filteredClients.length === 0 && (
              <div className="py-12 text-center text-slate-400 text-sm">
                {data.clients.length === 0 ? 'No reconciliation data' : 'No clients match filter'}
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
}
