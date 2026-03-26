'use client';

import { useEffect } from 'react';
import {
  useClients,
  useUploadLog,
  useRecomputeRisk,
  useDataStatus,
  useImpersonate,
  useDashboardAnalytics,
} from '@/hooks/useAdmin';
import { formatDate, formatINRShort, formatPct, formatIndianNumber, pnlColor } from '@/lib/format';
import Button from '@/components/ui/Button';
import Badge from '@/components/ui/Badge';
import Spinner from '@/components/ui/Spinner';
import {
  Users,
  Upload,
  RefreshCcw,
  AlertCircle,
  Calendar,
  Clock,
  Eye,
  TrendingUp,
  Wallet,
  PiggyBank,
  BarChart3,
  Shield,
  DollarSign,
  Percent,
} from 'lucide-react';

function StatCard({ label, value, subtitle, icon: Icon, color = 'teal' }) {
  const colorMap = {
    teal: 'text-teal-600 bg-teal-50',
    emerald: 'text-emerald-600 bg-emerald-50',
    red: 'text-red-600 bg-red-50',
    amber: 'text-amber-600 bg-amber-50',
    slate: 'text-slate-600 bg-slate-100',
    blue: 'text-blue-600 bg-blue-50',
  };
  const iconClasses = colorMap[color] || colorMap.teal;

  return (
    <div className="bg-white rounded-xl border border-slate-200 p-4">
      <div className="flex items-start justify-between mb-2">
        <p className="text-xs font-medium text-slate-500 uppercase tracking-wider">
          {label}
        </p>
        {Icon && (
          <div className={`p-1.5 rounded-lg ${iconClasses}`}>
            <Icon className="w-4 h-4" />
          </div>
        )}
      </div>
      <p className="text-xl font-bold font-mono text-slate-800">{value}</p>
      {subtitle && (
        <p className="text-xs text-slate-400 mt-1">{subtitle}</p>
      )}
    </div>
  );
}

function PerformerTable({ title, performers, icon: Icon, emptyText }) {
  if (!performers || performers.length === 0) {
    return null;
  }

  return (
    <div className="bg-white rounded-xl border border-slate-200 p-5">
      <div className="flex items-center gap-2 mb-3">
        {Icon && <Icon className="w-4 h-4 text-teal-600" />}
        <h3 className="text-sm font-semibold text-slate-800">{title}</h3>
      </div>
      <div className="space-y-2">
        {performers.map((p, i) => (
          <div
            key={p.client_id}
            className="flex items-center justify-between py-2 px-3 rounded-lg hover:bg-slate-50"
          >
            <div className="flex items-center gap-3">
              <span className="text-xs font-bold text-slate-400 w-5">
                {i + 1}
              </span>
              <div>
                <p className="text-sm font-medium text-slate-800">{p.name}</p>
                <p className="text-xs text-slate-400 font-mono">
                  {p.client_code}
                </p>
              </div>
            </div>
            <div className="text-right">
              <p className={`text-sm font-bold font-mono ${pnlColor(p.cagr)}`}>
                {formatPct(p.cagr)}
              </p>
              <p className="text-xs text-slate-400 font-mono">
                {formatINRShort(p.aum)}
              </p>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

export default function AdminDashboard() {
  const { data: clients, loading: clientsLoading, refetch: refetchClients } =
    useClients();
  const { data: logs, loading: logsLoading, refetch: refetchLogs } =
    useUploadLog();
  const { recompute, loading: recomputing } = useRecomputeRisk();
  const {
    data: dataStatus,
    loading: statusLoading,
    refetch: refetchStatus,
  } = useDataStatus();
  const { impersonate, loading: impersonating } = useImpersonate();
  const {
    data: analytics,
    loading: analyticsLoading,
    refetch: refetchAnalytics,
  } = useDashboardAnalytics();

  useEffect(() => {
    refetchClients();
    refetchLogs();
    refetchStatus();
    refetchAnalytics();
  }, [refetchClients, refetchLogs, refetchStatus, refetchAnalytics]);

  async function handleRecompute() {
    try {
      await recompute();
      alert('Risk metrics recomputed for all clients.');
      refetchAnalytics();
    } catch (err) {
      alert(`Recomputation failed: ${err.message}`);
    }
  }

  async function handleViewClient(clientId) {
    try {
      await impersonate(clientId);
      sessionStorage.setItem('admin_viewing', 'true');
      window.location.href = '/dashboard';
    } catch (err) {
      alert(`Failed to view client: ${err.message}`);
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-bold text-slate-800">Admin Dashboard</h2>
        <Button
          variant="secondary"
          size="sm"
          loading={recomputing}
          onClick={handleRecompute}
        >
          <RefreshCcw className="w-4 h-4" />
          Recompute All Risk Metrics
        </Button>
      </div>

      {/* Data Status Banner */}
      <div className="bg-white rounded-xl border border-slate-200 p-4">
        <div className="flex flex-wrap items-center gap-6 text-sm">
          <div className="flex items-center gap-2">
            <Clock className="w-4 h-4 text-teal-600" />
            <span className="text-slate-500">Last Updated On:</span>
            {statusLoading ? (
              <span className="text-slate-400">Loading...</span>
            ) : dataStatus?.last_uploaded_at ? (
              <span className="font-semibold text-slate-800">
                {formatDate(dataStatus.last_uploaded_at)}
              </span>
            ) : (
              <span className="text-slate-400">No uploads yet</span>
            )}
          </div>
          <div className="w-px h-5 bg-slate-200 hidden sm:block" />
          <div className="flex items-center gap-2">
            <Calendar className="w-4 h-4 text-teal-600" />
            <span className="text-slate-500">Last Date in File:</span>
            {statusLoading ? (
              <span className="text-slate-400">Loading...</span>
            ) : dataStatus?.last_data_date ? (
              <span className="font-semibold text-slate-800">
                {formatDate(dataStatus.last_data_date)}
              </span>
            ) : (
              <span className="text-slate-400">No data</span>
            )}
          </div>
          {analytics?.data_as_of && (
            <>
              <div className="w-px h-5 bg-slate-200 hidden sm:block" />
              <div className="flex items-center gap-2">
                <BarChart3 className="w-4 h-4 text-teal-600" />
                <span className="text-slate-500">Analytics as of:</span>
                <span className="font-semibold text-slate-800">
                  {formatDate(analytics.data_as_of)}
                </span>
              </div>
            </>
          )}
        </div>
      </div>

      {/* Analytics Cards */}
      {analyticsLoading ? (
        <div className="flex justify-center py-8">
          <Spinner />
        </div>
      ) : analytics ? (
        <>
          <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-4">
            <StatCard
              label="Total AUM"
              value={formatINRShort(analytics.total_aum)}
              subtitle={`${analytics.total_clients} active clients`}
              icon={DollarSign}
              color="teal"
            />
            <StatCard
              label="Total Invested"
              value={formatINRShort(analytics.total_invested)}
              icon={PiggyBank}
              color="slate"
            />
            <StatCard
              label="Total Profit"
              value={formatINRShort(analytics.total_profit)}
              subtitle={formatPct(analytics.total_profit_pct)}
              icon={TrendingUp}
              color={analytics.total_profit >= 0 ? 'emerald' : 'red'}
            />
            <StatCard
              label="Blended CAGR"
              value={formatPct(analytics.blended_cagr)}
              subtitle="AUM-weighted"
              icon={BarChart3}
              color="teal"
            />
            <StatCard
              label="Total Cash"
              value={formatINRShort(analytics.total_cash)}
              subtitle={`${Number(analytics.total_cash_pct || 0).toFixed(1)}% of AUM`}
              icon={Wallet}
              color="amber"
            />
          </div>

          {/* Top Performers */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            <PerformerTable
              title="Top 5 Performers (by CAGR)"
              performers={analytics.top_performers}
              icon={TrendingUp}
            />
          </div>
        </>
      ) : null}

      {/* Client List */}
      <div className="bg-white rounded-xl border border-slate-200 p-5">
        <div className="flex items-center gap-2 mb-4">
          <Users className="w-5 h-5 text-teal-600" />
          <h3 className="text-base font-semibold text-slate-800">Clients</h3>
          <span className="text-xs text-slate-400 ml-1">
            (click to view portfolio)
          </span>
        </div>

        {clientsLoading ? (
          <div className="flex justify-center py-8">
            <Spinner />
          </div>
        ) : !clients || clients.length === 0 ? (
          <p className="text-sm text-slate-400 py-4">No clients found.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-slate-50 border-b border-slate-200">
                  <th className="px-3 py-2 text-left text-xs font-semibold text-slate-400 uppercase">
                    Name
                  </th>
                  <th className="px-3 py-2 text-left text-xs font-semibold text-slate-400 uppercase">
                    Username
                  </th>
                  <th className="px-3 py-2 text-left text-xs font-semibold text-slate-400 uppercase">
                    Code
                  </th>
                  <th className="px-3 py-2 text-left text-xs font-semibold text-slate-400 uppercase">
                    Status
                  </th>
                  <th className="px-3 py-2 text-left text-xs font-semibold text-slate-400 uppercase">
                    Last Login
                  </th>
                  <th className="px-3 py-2 text-center text-xs font-semibold text-slate-400 uppercase">
                    View
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {(Array.isArray(clients) ? clients : []).map((c) => (
                  <tr
                    key={c.id}
                    className="hover:bg-teal-50 cursor-pointer transition-colors"
                    onClick={() => !c.is_admin && handleViewClient(c.id)}
                  >
                    <td className="px-3 py-2 font-medium text-slate-800">
                      {c.name}
                    </td>
                    <td className="px-3 py-2 text-slate-600 font-mono text-xs">
                      {c.username}
                    </td>
                    <td className="px-3 py-2 text-slate-600 font-mono text-xs">
                      {c.client_code}
                    </td>
                    <td className="px-3 py-2">
                      <Badge variant={c.is_active ? 'active' : 'inactive'}>
                        {c.is_active ? 'Active' : 'Inactive'}
                      </Badge>
                    </td>
                    <td className="px-3 py-2 text-xs text-slate-500">
                      {c.last_login ? formatDate(c.last_login) : 'Never'}
                    </td>
                    <td className="px-3 py-2 text-center">
                      {c.is_admin ? (
                        <span className="text-xs text-slate-300">-</span>
                      ) : (
                        <button
                          className="inline-flex items-center gap-1 text-xs text-teal-600 hover:text-teal-800 font-medium"
                          onClick={(e) => {
                            e.stopPropagation();
                            handleViewClient(c.id);
                          }}
                          disabled={impersonating}
                        >
                          <Eye className="w-3.5 h-3.5" />
                          View
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Upload Log */}
      <div className="bg-white rounded-xl border border-slate-200 p-5">
        <div className="flex items-center gap-2 mb-4">
          <Upload className="w-5 h-5 text-teal-600" />
          <h3 className="text-base font-semibold text-slate-800">
            Recent Uploads
          </h3>
        </div>

        {logsLoading ? (
          <div className="flex justify-center py-8">
            <Spinner />
          </div>
        ) : !logs || logs.length === 0 ? (
          <p className="text-sm text-slate-400 py-4">No uploads yet.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-slate-50 border-b border-slate-200">
                  <th className="px-3 py-2 text-left text-xs font-semibold text-slate-400 uppercase">
                    Date
                  </th>
                  <th className="px-3 py-2 text-left text-xs font-semibold text-slate-400 uppercase">
                    Type
                  </th>
                  <th className="px-3 py-2 text-left text-xs font-semibold text-slate-400 uppercase">
                    Filename
                  </th>
                  <th className="px-3 py-2 text-right text-xs font-semibold text-slate-400 uppercase">
                    Processed
                  </th>
                  <th className="px-3 py-2 text-right text-xs font-semibold text-slate-400 uppercase">
                    Failed
                  </th>
                  <th className="px-3 py-2 text-left text-xs font-semibold text-slate-400 uppercase">
                    Status
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {(Array.isArray(logs) ? logs : []).map((log) => (
                  <tr key={log.id} className="hover:bg-slate-50">
                    <td className="px-3 py-2 text-xs text-slate-600">
                      {formatDate(log.uploaded_at)}
                    </td>
                    <td className="px-3 py-2">
                      <Badge
                        variant={
                          log.file_type === 'nav' ? 'active' : 'pending'
                        }
                      >
                        {log.file_type?.toUpperCase()}
                      </Badge>
                    </td>
                    <td className="px-3 py-2 text-xs text-slate-600 font-mono truncate max-w-xs">
                      {log.filename}
                    </td>
                    <td className="px-3 py-2 text-right font-mono text-xs">
                      {log.rows_processed}
                    </td>
                    <td className="px-3 py-2 text-right font-mono text-xs text-red-600">
                      {log.rows_failed}
                    </td>
                    <td className="px-3 py-2">
                      {log.rows_failed > 0 ? (
                        <span className="flex items-center gap-1 text-xs text-amber-600">
                          <AlertCircle className="w-3 h-3" /> Warnings
                        </span>
                      ) : (
                        <Badge variant="success">OK</Badge>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
