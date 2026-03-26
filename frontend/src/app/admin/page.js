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
import { formatDate, formatINRShort, formatPct } from '@/lib/format';
import Button from '@/components/ui/Button';
import Spinner from '@/components/ui/Spinner';
import {
  RefreshCcw,
  Clock,
  Calendar,
  TrendingUp,
  Wallet,
  PiggyBank,
  BarChart3,
  DollarSign,
  LineChart,
} from 'lucide-react';
import StatCard from '@/components/admin/StatCard';
import PerformerTable from '@/components/admin/PerformerTable';
import ClientListTable from '@/components/admin/ClientListTable';
import UploadLogTable from '@/components/admin/UploadLogTable';
import AggregateNavChart from '@/components/admin/AggregateNavChart';
import AggregatePerformance from '@/components/admin/AggregatePerformance';
import AggregateAllocation from '@/components/admin/AggregateAllocation';
import AggregateRiskScorecard from '@/components/admin/AggregateRiskScorecard';
import AggregateMonthlyReturns from '@/components/admin/AggregateMonthlyReturns';

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
      ) : null}

      {/* Aggregate Portfolio Dashboard */}
      <div className="border-t border-slate-200 pt-6">
        <div className="flex items-center gap-2 mb-4">
          <LineChart className="w-5 h-5 text-teal-600" />
          <h3 className="text-lg font-bold text-slate-800">
            Aggregate Portfolio Dashboard
          </h3>
          <span className="text-xs text-slate-400 ml-1">
            Composite view across all clients
          </span>
        </div>
      </div>

      <AggregateNavChart />
      <AggregatePerformance />

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <AggregateAllocation />
        <AggregateRiskScorecard />
      </div>

      <AggregateMonthlyReturns />

      {/* Top Performers / Investors */}
      {analytics && (
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
          <PerformerTable
            title="Top 5 by CAGR"
            performers={analytics.top_performers}
            icon={TrendingUp}
            valueKey="cagr"
            valueFormat="pct"
            subtitleKey="aum"
          />
          <PerformerTable
            title="Top 5 by Current NAV"
            performers={analytics.top_by_nav}
            icon={DollarSign}
            valueKey="aum"
            valueFormat="inr"
            subtitleKey="invested"
          />
          <PerformerTable
            title="Top 5 by Invested Capital"
            performers={analytics.top_by_invested}
            icon={PiggyBank}
            valueKey="invested"
            valueFormat="inr"
            subtitleKey="aum"
          />
        </div>
      )}

      <ClientListTable
        clients={clients}
        loading={clientsLoading}
        impersonating={impersonating}
        onViewClient={handleViewClient}
      />

      <UploadLogTable logs={logs} loading={logsLoading} />
    </div>
  );
}
