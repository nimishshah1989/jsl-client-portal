'use client';

import { useState, useCallback, useMemo } from 'react';
import { apiFetch } from '@/lib/api';
import { formatINRShort } from '@/lib/format';
import { Upload, Download, Search, Filter } from 'lucide-react';
import ReconciliationClientRow from '@/components/admin/ReconciliationClientRow';

function SummaryCard({ label, value, subtext, color = 'text-slate-800' }) {
  return (
    <div className="bg-white rounded-xl border border-slate-200 p-4">
      <p className="text-sm text-slate-500">{label}</p>
      <p className={`text-2xl font-bold font-mono ${color}`}>{value}</p>
      {subtext && <p className="text-xs text-slate-400 mt-1">{subtext}</p>}
    </div>
  );
}

function pctColor(value, greenThreshold = 1, amberThreshold = 3) {
  const abs = Math.abs(value);
  if (abs <= greenThreshold) return 'text-emerald-600';
  if (abs <= amberThreshold) return 'text-amber-600';
  return 'text-red-600';
}

export default function ReconciliationPage() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [initialLoading, setInitialLoading] = useState(true);
  const [error, setError] = useState(null);
  const [expandedClients, setExpandedClients] = useState(new Set());
  const [searchTerm, setSearchTerm] = useState('');
  const [statusFilter, setStatusFilter] = useState('ALL');

  // Load last reconciliation from DB on mount
  useState(() => {
    (async () => {
      try {
        const result = await apiFetch('/admin/reconciliation/summary');
        setData(result);
      } catch {
        // No saved data — fine
      } finally {
        setInitialLoading(false);
      }
    })();
  });

  const handleUpload = useCallback(async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setLoading(true);
    setError(null);
    const formData = new FormData();
    formData.append('file', file);
    try {
      const result = await apiFetch('/admin/reconciliation/upload', { method: 'POST', body: formData });
      setData(result);
    } catch (err) {
      setError(err.message || 'Upload failed');
    } finally {
      setLoading(false);
    }
  }, []);

  const handleExport = useCallback(async () => {
    try {
      const response = await fetch('/api/admin/reconciliation/export', { credentials: 'include' });
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = 'reconciliation_mismatches.csv';
      a.click();
      URL.revokeObjectURL(url);
    } catch {
      setError('Export failed');
    }
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

  // 3-way value helpers
  const navTotal    = Number(data?.total_nav_value || 0);
  const navEquity   = Number(data?.total_nav_equity_value || 0);
  const navEtf      = Number(data?.total_etf_value || 0);
  const navCash     = Number(data?.total_cash_value || 0);
  const boTotal     = Number(data?.total_bo_holdings_value || 0);
  const ourTotal    = Number(data?.total_our_holdings_value || 0);
  const ourEtfTotal = Number(data?.total_our_etf_holdings_value || 0);
  // Use equity-only diff (nav minus ETF minus cash) vs BO — this is the correct check.
  // total_nav_vs_bo_diff includes ETF+cash and will always look large; ignore it for display.
  const navEquityVsBo    = Number(data?.total_nav_equity_vs_bo_diff || 0);
  const boVsOurs         = Number(data?.total_bo_vs_ours_diff || 0);
  const etfVsOurs        = Number(data?.total_etf_vs_ours_diff || 0);
  const navEquityVsBoPct = navEquity > 0 ? (navEquityVsBo / navEquity * 100) : 0;
  const boVsOursPct      = boTotal > 0 ? (boVsOurs / boTotal * 100) : 0;
  const etfVsOursPct     = navEtf > 0 ? (etfVsOurs / navEtf * 100) : 0;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-semibold text-slate-800">3-Way Holdings Reconciliation</h2>
          <p className="text-sm text-slate-500 mt-1">
            NAV file vs Holding Report vs Transaction-derived holdings
          </p>
        </div>
        {data && (
          <div className="flex items-center gap-2">
            {data.total_cost_mismatches > 0 && (
              <button
                onClick={async () => {
                  if (!confirm(`Sync avg cost for ${data.total_cost_mismatches} cost mismatches from backoffice?`)) return;
                  try {
                    const r = await apiFetch('/admin/reconciliation/sync-costs', { method: 'POST' });
                    alert(`Synced ${r.updated} holdings. Re-upload holding report to verify.`);
                  } catch (err) {
                    setError(err.message || 'Sync failed');
                  }
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

      {/* Upload */}
      <div className="bg-white rounded-xl border border-slate-200 p-6">
        <label className={`flex flex-col items-center justify-center w-full h-32 border-2 border-dashed rounded-lg cursor-pointer transition-colors ${loading ? 'border-teal-300 bg-teal-50' : 'border-slate-300 hover:border-teal-400 hover:bg-teal-50/50'}`}>
          <div className="flex flex-col items-center">
            {loading ? (
              <>
                <div className="w-8 h-8 border-2 border-teal-500 border-t-transparent rounded-full animate-spin" />
                <p className="text-sm text-teal-600 mt-2">Reconciling...</p>
              </>
            ) : (
              <>
                <Upload className="w-8 h-8 text-slate-400" />
                <p className="text-sm text-slate-600 mt-2">Upload Holding Report (.xlsx)</p>
                <p className="text-xs text-slate-400">Click or drag file here</p>
              </>
            )}
          </div>
          <input type="file" accept=".xlsx,.xls" onChange={handleUpload} disabled={loading} className="hidden" />
        </label>
      </div>

      {error && <div className="bg-red-50 border border-red-200 rounded-lg p-4 text-sm text-red-700">{error}</div>}

      {data && (
        <>
          {/* 3-Way Value Comparison */}
          <div className="bg-white rounded-xl border border-slate-200 p-5 space-y-4">
            <div>
              <h3 className="text-sm font-semibold text-slate-700 uppercase tracking-wider mb-0.5">4-Component NAV Breakdown</h3>
              <p className="text-xs text-slate-400">NAV = Equity + ETF + Cash. Compare each component independently against its source.</p>
            </div>

            {/* Row 1: NAV breakdown + equity reconciliation */}
            <div>
              <p className="text-xs font-medium text-slate-500 mb-2">Equity reconciliation (NAV equity ≈ BO ≈ Ours)</p>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                <SummaryCard label="NAV Equity" value={formatINRShort(navEquity)} subtext="NAV minus ETF minus cash" />
                <SummaryCard label="BO Holdings" value={formatINRShort(boTotal)} subtext="Equity holding report total" />
                <SummaryCard
                  label="NAV Equity vs BO"
                  value={formatINRShort(navEquityVsBo)}
                  subtext={`${navEquityVsBoPct >= 0 ? '+' : ''}${navEquityVsBoPct.toFixed(3)}% — should be 0`}
                  color={pctColor(navEquityVsBoPct, 0.1, 0.5)}
                />
                <SummaryCard
                  label="BO vs Ours (FIFO)"
                  value={formatINRShort(boVsOurs)}
                  subtext={`${boVsOursPct >= 0 ? '+' : ''}${boVsOursPct.toFixed(2)}% — transaction gap`}
                  color={pctColor(boVsOursPct)}
                />
              </div>
            </div>

            {/* Row 2: ETF reconciliation */}
            <div>
              <p className="text-xs font-medium text-slate-500 mb-2">ETF reconciliation (NAV ETF ≈ Our ETF holdings — upload ETF Holding File to populate)</p>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                <SummaryCard label="NAV ETF" value={formatINRShort(navEtf)} subtext="Investments in ETF column" />
                <SummaryCard label="Our ETF Holdings" value={formatINRShort(ourEtfTotal)} subtext={ourEtfTotal > 0 ? `${data.total_structural_etf || 0} positions priced` : 'Upload ETF Holding File'} color={ourEtfTotal > 0 ? 'text-slate-800' : 'text-amber-600'} />
                <SummaryCard
                  label="ETF vs Ours"
                  value={formatINRShort(etfVsOurs)}
                  subtext={ourEtfTotal > 0 ? `${etfVsOursPct >= 0 ? '+' : ''}${etfVsOursPct.toFixed(2)}% — should be ~0` : 'No ETF prices yet'}
                  color={ourEtfTotal > 0 ? pctColor(etfVsOursPct, 1, 3) : 'text-amber-600'}
                />
                <SummaryCard label="NAV Cash" value={formatINRShort(navCash)} subtext="Cash + bank balance" />
              </div>
            </div>

            <p className="text-xs text-slate-400">
              NAV Total: <span className="font-mono font-medium text-slate-600">{formatINRShort(navTotal)}</span>
              {' '}({data.clients_with_nav || 0} clients)
            </p>
          </div>

          {/* Issue count cards */}
          <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-7 gap-3">
            <SummaryCard label="Client Accuracy" value={`${data.client_match_pct || 0}%`}
              subtext={`${data.clients_fully_matched || 0} of ${data.total_clients_bo} clean`}
              color={data.client_match_pct >= 90 ? 'text-emerald-600' : data.client_match_pct >= 70 ? 'text-amber-600' : 'text-red-600'} />
            <SummaryCard label="Clients" value={data.total_clients_bo} subtext={`${data.total_clients_matched} in our system`} />
            <SummaryCard label="Qty Mismatches" value={data.total_qty_mismatches}
              color={data.total_qty_mismatches > 0 ? 'text-amber-600' : 'text-emerald-600'} />
            <SummaryCard label="Cost Mismatches" value={data.total_cost_mismatches}
              color={data.total_cost_mismatches > 0 ? 'text-orange-600' : 'text-emerald-600'} />
            <SummaryCard label="Missing in Ours" value={data.total_missing_in_ours}
              color={data.total_missing_in_ours > 0 ? 'text-red-600' : 'text-emerald-600'} />
            <SummaryCard label="Extra (Genuine)" value={data.total_extra_in_ours || 0}
              subtext="EQ positions not in BO"
              color={(data.total_extra_in_ours || 0) > 0 ? 'text-blue-600' : 'text-emerald-600'} />
            <SummaryCard label="ETF/MF (Structural)" value={data.total_structural_etf || 0}
              subtext="Expected — tracked via NAV ETF col"
              color="text-slate-500" />
          </div>

          <div className="flex items-center gap-4 text-xs text-slate-400">
            {data.market_date && <span>BO as of: <span className="font-medium text-slate-600">{data.market_date}</span></span>}
            {data.run_at && <span>Reconciled: <span className="font-medium text-slate-600">{new Date(data.run_at).toLocaleString('en-IN')}</span></span>}
            <span>Our Value = our qty × BO market price (apples-to-apples)</span>
          </div>

          {/* Commentary */}
          {data.commentary?.length > 0 && (
            <div className="bg-white rounded-xl border border-slate-200 p-5 space-y-3">
              <h3 className="text-sm font-semibold text-slate-700 uppercase tracking-wider">Insights</h3>
              {data.commentary.map((c, i) => {
                const styles = { critical: 'border-l-red-500 bg-red-50', high: 'border-l-amber-500 bg-amber-50', medium: 'border-l-yellow-400 bg-yellow-50', good: 'border-l-emerald-500 bg-emerald-50', info: 'border-l-blue-400 bg-blue-50' };
                const text = { critical: 'text-red-800', high: 'text-amber-800', medium: 'text-yellow-800', good: 'text-emerald-800', info: 'text-blue-800' };
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

          {/* Filters */}
          <div className="flex items-center gap-4">
            <div className="relative flex-1 max-w-xs">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />
              <input type="text" placeholder="Search client code, name, or group..." value={searchTerm}
                onChange={e => setSearchTerm(e.target.value)}
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

          {/* Client Table */}
          <div className="bg-white rounded-xl border border-slate-200 overflow-hidden">
            <table className="w-full">
              <thead>
                <tr className="bg-slate-50 border-b border-slate-200">
                  <th className="px-3 py-3 w-8" />
                  <th className="px-3 py-3 text-left text-xs font-semibold text-slate-500 uppercase tracking-wider">Code</th>
                  <th className="px-3 py-3 text-left text-xs font-semibold text-slate-500 uppercase tracking-wider">Name</th>
                  <th className="px-3 py-3 text-right text-xs font-semibold text-slate-500 uppercase tracking-wider">NAV Total</th>
                  <th className="px-3 py-3 text-right text-xs font-semibold text-slate-500 uppercase tracking-wider">BO Value</th>
                  <th className="px-3 py-3 text-right text-xs font-semibold text-slate-500 uppercase tracking-wider">Our Value</th>
                  <th className="px-3 py-3 text-right text-xs font-semibold text-slate-500 uppercase tracking-wider">BO vs Ours</th>
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
