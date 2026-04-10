'use client';

import { useState, useCallback, useMemo } from 'react';
import { apiFetch } from '@/lib/api';
import { formatINR, formatIndianNumber, pnlColor } from '@/lib/format';
import {
  Upload,
  CheckCircle2,
  AlertTriangle,
  XCircle,
  ChevronDown,
  ChevronRight,
  Download,
  Search,
  Filter,
} from 'lucide-react';

const STATUS_CONFIG = {
  MATCH: { label: 'Match', color: 'bg-emerald-100 text-emerald-700', icon: CheckCircle2 },
  QTY_MISMATCH: { label: 'Qty Mismatch', color: 'bg-amber-100 text-amber-700', icon: AlertTriangle },
  COST_MISMATCH: { label: 'Cost Mismatch', color: 'bg-orange-100 text-orange-700', icon: AlertTriangle },
  VALUE_MISMATCH: { label: 'Value Mismatch', color: 'bg-yellow-100 text-yellow-700', icon: AlertTriangle },
  MISSING_IN_OURS: { label: 'Missing', color: 'bg-red-100 text-red-700', icon: XCircle },
  EXTRA_IN_OURS: { label: 'Extra', color: 'bg-blue-100 text-blue-700', icon: AlertTriangle },
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

function SummaryCard({ label, value, subtext, color = 'text-slate-800' }) {
  return (
    <div className="bg-white rounded-xl border border-slate-200 p-4">
      <p className="text-sm text-slate-500">{label}</p>
      <p className={`text-2xl font-bold font-mono ${color}`}>{value}</p>
      {subtext && <p className="text-xs text-slate-400 mt-1">{subtext}</p>}
    </div>
  );
}

function ClientRow({ client, expanded, onToggle }) {
  const issues = client.qty_mismatch_count + client.cost_mismatch_count +
    client.value_mismatch_count + client.missing_in_ours_count + client.extra_in_ours_count;

  return (
    <>
      <tr
        className="border-b border-slate-100 hover:bg-slate-50 cursor-pointer"
        onClick={onToggle}
      >
        <td className="px-4 py-3">
          {expanded ? <ChevronDown className="w-4 h-4 text-slate-400" /> : <ChevronRight className="w-4 h-4 text-slate-400" />}
        </td>
        <td className="px-4 py-3 font-mono text-sm font-medium text-slate-800">{client.client_code}</td>
        <td className="px-4 py-3 text-sm text-slate-600 truncate max-w-[180px]" title={client.client_name}>{client.client_name || '--'}</td>
        <td className="px-4 py-3 text-sm text-slate-600">{client.family_group}</td>
        <td className="px-4 py-3 text-sm font-mono text-center">{client.total_holdings_bo}</td>
        <td className="px-4 py-3 text-sm font-mono text-center">{client.total_holdings_ours}</td>
        <td className="px-4 py-3 text-center">
          <span className={`font-mono text-sm font-medium ${client.match_pct === 100 ? 'text-emerald-600' : 'text-amber-600'}`}>
            {client.match_pct}%
          </span>
        </td>
        <td className="px-4 py-3 text-center">
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
          <td colSpan={8} className="px-0 py-0">
            <div className="bg-slate-50 border-y border-slate-200">
              <table className="w-full text-sm">
                <thead>
                  <tr className="bg-slate-100">
                    <th className="px-4 py-2 text-left text-xs font-semibold text-slate-500 uppercase">Symbol</th>
                    <th className="px-4 py-2 text-left text-xs font-semibold text-slate-500 uppercase">Status</th>
                    <th className="px-4 py-2 text-right text-xs font-semibold text-slate-500 uppercase">BO Qty</th>
                    <th className="px-4 py-2 text-right text-xs font-semibold text-slate-500 uppercase">Our Qty</th>
                    <th className="px-4 py-2 text-right text-xs font-semibold text-slate-500 uppercase">Qty Diff</th>
                    <th className="px-4 py-2 text-right text-xs font-semibold text-slate-500 uppercase">BO Avg Cost</th>
                    <th className="px-4 py-2 text-right text-xs font-semibold text-slate-500 uppercase">Our Avg Cost</th>
                    <th className="px-4 py-2 text-right text-xs font-semibold text-slate-500 uppercase">Cost Diff</th>
                    <th className="px-4 py-2 text-right text-xs font-semibold text-slate-500 uppercase">BO Value</th>
                    <th className="px-4 py-2 text-right text-xs font-semibold text-slate-500 uppercase">Our Value</th>
                  </tr>
                </thead>
                <tbody>
                  {client.matches.map((m, i) => (
                    <tr key={i} className={`border-b border-slate-100 ${m.status !== 'MATCH' ? 'bg-amber-50/50' : ''}`}>
                      <td className="px-4 py-2 font-mono font-medium text-slate-800">{m.symbol}</td>
                      <td className="px-4 py-2"><StatusBadge status={m.status} /></td>
                      <td className="px-4 py-2 text-right font-mono">{m.bo_quantity ?? '--'}</td>
                      <td className="px-4 py-2 text-right font-mono">{m.our_quantity ?? '--'}</td>
                      <td className={`px-4 py-2 text-right font-mono ${m.qty_diff && Number(m.qty_diff) !== 0 ? 'text-red-600 font-medium' : 'text-slate-400'}`}>
                        {m.qty_diff != null ? Number(m.qty_diff) : '--'}
                      </td>
                      <td className="px-4 py-2 text-right font-mono">{m.bo_avg_cost != null ? formatINR(Number(m.bo_avg_cost), 2) : '--'}</td>
                      <td className="px-4 py-2 text-right font-mono">{m.our_avg_cost != null ? formatINR(Number(m.our_avg_cost), 2) : '--'}</td>
                      <td className={`px-4 py-2 text-right font-mono ${m.cost_diff && Math.abs(Number(m.cost_diff)) > 0.02 ? 'text-red-600 font-medium' : 'text-slate-400'}`}>
                        {m.cost_diff != null ? formatINR(Number(m.cost_diff), 4) : '--'}
                      </td>
                      <td className="px-4 py-2 text-right font-mono">{m.bo_market_value != null ? formatINR(Number(m.bo_market_value)) : '--'}</td>
                      <td className="px-4 py-2 text-right font-mono">{m.our_market_value != null ? formatINR(Number(m.our_market_value)) : '--'}</td>
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

export default function ReconciliationPage() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [initialLoading, setInitialLoading] = useState(true);
  const [error, setError] = useState(null);
  const [expandedClients, setExpandedClients] = useState(new Set());
  const [searchTerm, setSearchTerm] = useState('');
  const [statusFilter, setStatusFilter] = useState('ALL'); // ALL | ISSUES_ONLY | MATCH_ONLY

  // Load last reconciliation from DB on mount
  useState(() => {
    (async () => {
      try {
        const result = await apiFetch('/admin/reconciliation/summary');
        setData(result);
      } catch {
        // No saved data — that's fine
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
      const result = await apiFetch('/admin/reconciliation/upload', {
        method: 'POST',
        body: formData,
      });
      setData(result);
    } catch (err) {
      setError(err.message || 'Upload failed');
    } finally {
      setLoading(false);
    }
  }, []);

  const handleExport = useCallback(async () => {
    try {
      const response = await fetch('/api/admin/reconciliation/export', {
        credentials: 'include',
      });
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = 'reconciliation_mismatches.csv';
      a.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      setError('Export failed');
    }
  }, []);

  const toggleClient = useCallback((code) => {
    setExpandedClients(prev => {
      const next = new Set(prev);
      if (next.has(code)) next.delete(code);
      else next.add(code);
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

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-semibold text-slate-800">Holdings Reconciliation</h2>
          <p className="text-sm text-slate-500 mt-1">
            Compare backoffice Holding Report against computed holdings
          </p>
        </div>
        {data && (
          <button
            onClick={handleExport}
            className="flex items-center gap-2 px-4 py-2 text-sm font-medium text-slate-600 bg-white border border-slate-200 rounded-lg hover:bg-slate-50"
          >
            <Download className="w-4 h-4" /> Export Mismatches
          </button>
        )}
      </div>

      {/* Upload Section */}
      <div className="bg-white rounded-xl border border-slate-200 p-6">
        <label className={`flex flex-col items-center justify-center w-full h-32 border-2 border-dashed rounded-lg cursor-pointer transition-colors ${
          loading ? 'border-teal-300 bg-teal-50' : 'border-slate-300 hover:border-teal-400 hover:bg-teal-50/50'
        }`}>
          <div className="flex flex-col items-center">
            {loading ? (
              <>
                <div className="w-8 h-8 border-2 border-teal-500 border-t-transparent rounded-full animate-spin" />
                <p className="text-sm text-teal-600 mt-2">Reconciling...</p>
              </>
            ) : (
              <>
                <Upload className="w-8 h-8 text-slate-400" />
                <p className="text-sm text-slate-600 mt-2">
                  Upload Holding Report (.xlsx)
                </p>
                <p className="text-xs text-slate-400">Click or drag file here</p>
              </>
            )}
          </div>
          <input
            type="file"
            accept=".xlsx,.xls"
            onChange={handleUpload}
            disabled={loading}
            className="hidden"
          />
        </label>
      </div>

      {error && (
        <div className="bg-red-50 border border-red-200 rounded-lg p-4 text-sm text-red-700">
          {error}
        </div>
      )}

      {/* Summary Cards */}
      {data && (
        <>
          <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-4">
            <SummaryCard
              label="Clients (Backoffice)"
              value={data.total_clients_bo}
              subtext={`${data.total_clients_matched} found in our system`}
            />
            <SummaryCard
              label="Holdings (Backoffice)"
              value={data.total_holdings_bo}
              subtext={`${data.total_holdings_matched} matched`}
              color={data.total_holdings_matched === data.total_holdings_bo ? 'text-emerald-600' : 'text-slate-800'}
            />
            <SummaryCard
              label="Match Rate"
              value={`${data.match_pct}%`}
              color={data.match_pct >= 95 ? 'text-emerald-600' : data.match_pct >= 80 ? 'text-amber-600' : 'text-red-600'}
            />
            <SummaryCard
              label="Qty Mismatches"
              value={data.total_qty_mismatches}
              color={data.total_qty_mismatches > 0 ? 'text-amber-600' : 'text-emerald-600'}
            />
            <SummaryCard
              label="Cost Mismatches"
              value={data.total_cost_mismatches}
              color={data.total_cost_mismatches > 0 ? 'text-orange-600' : 'text-emerald-600'}
            />
            <SummaryCard
              label="Missing in Ours"
              value={data.total_missing_in_ours}
              color={data.total_missing_in_ours > 0 ? 'text-red-600' : 'text-emerald-600'}
            />
          </div>

          <div className="flex items-center gap-4 text-xs text-slate-400">
            {data.market_date && (
              <span>Holding Report as of: <span className="font-medium text-slate-600">{data.market_date}</span></span>
            )}
            {data.run_at && (
              <span>Reconciled: <span className="font-medium text-slate-600">{new Date(data.run_at).toLocaleString('en-IN')}</span></span>
            )}
            {data.filename && (
              <span>File: <span className="font-medium text-slate-600">{data.filename}</span></span>
            )}
            <span>Match % = matched instruments / total instruments per client</span>
          </div>

          {/* Commentary / Insights */}
          {data.commentary && data.commentary.length > 0 && (
            <div className="bg-white rounded-xl border border-slate-200 p-5 space-y-3">
              <h3 className="text-sm font-semibold text-slate-700 uppercase tracking-wider">Reconciliation Insights</h3>
              {data.commentary.map((c, i) => {
                const severityStyles = {
                  critical: 'border-l-red-500 bg-red-50',
                  high: 'border-l-amber-500 bg-amber-50',
                  medium: 'border-l-yellow-400 bg-yellow-50',
                  good: 'border-l-emerald-500 bg-emerald-50',
                };
                const severityText = {
                  critical: 'text-red-800',
                  high: 'text-amber-800',
                  medium: 'text-yellow-800',
                  good: 'text-emerald-800',
                };
                return (
                  <div key={i} className={`border-l-4 rounded-r-lg p-3 ${severityStyles[c.severity] || 'bg-slate-50 border-l-slate-300'}`}>
                    <div className="flex items-start justify-between gap-2">
                      <p className={`text-sm font-medium ${severityText[c.severity] || 'text-slate-800'}`}>
                        {c.title}
                      </p>
                      {c.affected_clients > 0 && (
                        <span className="text-xs text-slate-500 whitespace-nowrap">{c.affected_clients} clients</span>
                      )}
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
              <input
                type="text"
                placeholder="Search by client code or group..."
                value={searchTerm}
                onChange={e => setSearchTerm(e.target.value)}
                className="w-full pl-9 pr-4 py-2 text-sm border border-slate-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-teal-500 focus:border-transparent"
              />
            </div>
            <div className="flex items-center gap-2">
              <Filter className="w-4 h-4 text-slate-400" />
              {['ALL', 'ISSUES_ONLY', 'MATCH_ONLY'].map(f => (
                <button
                  key={f}
                  onClick={() => setStatusFilter(f)}
                  className={`px-3 py-1.5 text-xs font-medium rounded-lg transition-colors ${
                    statusFilter === f
                      ? 'bg-teal-100 text-teal-700'
                      : 'bg-slate-100 text-slate-500 hover:bg-slate-200'
                  }`}
                >
                  {f === 'ALL' ? 'All' : f === 'ISSUES_ONLY' ? 'Issues Only' : 'Clean Only'}
                </button>
              ))}
            </div>
            <span className="text-xs text-slate-400">
              {filteredClients.length} of {data.clients.length} clients
            </span>
          </div>

          {/* Client Table */}
          <div className="bg-white rounded-xl border border-slate-200 overflow-hidden">
            <table className="w-full">
              <thead>
                <tr className="bg-slate-50 border-b border-slate-200">
                  <th className="px-4 py-3 w-8" />
                  <th className="px-4 py-3 text-left text-xs font-semibold text-slate-500 uppercase tracking-wider">Client Code</th>
                  <th className="px-4 py-3 text-left text-xs font-semibold text-slate-500 uppercase tracking-wider">Client Name</th>
                  <th className="px-4 py-3 text-left text-xs font-semibold text-slate-500 uppercase tracking-wider">Family Group</th>
                  <th className="px-4 py-3 text-center text-xs font-semibold text-slate-500 uppercase tracking-wider">BO Holdings</th>
                  <th className="px-4 py-3 text-center text-xs font-semibold text-slate-500 uppercase tracking-wider">Our Holdings</th>
                  <th className="px-4 py-3 text-center text-xs font-semibold text-slate-500 uppercase tracking-wider">Match %</th>
                  <th className="px-4 py-3 text-center text-xs font-semibold text-slate-500 uppercase tracking-wider">Issues</th>
                </tr>
              </thead>
              <tbody>
                {filteredClients.map(client => (
                  <ClientRow
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
