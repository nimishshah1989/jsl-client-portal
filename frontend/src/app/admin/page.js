'use client';

import { useEffect } from 'react';
import { useClients, useUploadLog, useRecomputeRisk } from '@/hooks/useAdmin';
import { formatDate } from '@/lib/format';
import Button from '@/components/ui/Button';
import Badge from '@/components/ui/Badge';
import Spinner from '@/components/ui/Spinner';
import { Users, Upload, RefreshCcw, AlertCircle } from 'lucide-react';

export default function AdminDashboard() {
  const { data: clients, loading: clientsLoading, refetch: refetchClients } = useClients();
  const { data: logs, loading: logsLoading, refetch: refetchLogs } = useUploadLog();
  const { recompute, loading: recomputing } = useRecomputeRisk();

  useEffect(() => {
    refetchClients();
    refetchLogs();
  }, [refetchClients, refetchLogs]);

  async function handleRecompute() {
    try {
      await recompute();
      alert('Risk metrics recomputed for all clients.');
    } catch (err) {
      alert(`Recomputation failed: ${err.message}`);
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-bold text-slate-800">Admin Dashboard</h2>
        <Button variant="secondary" size="sm" loading={recomputing} onClick={handleRecompute}>
          <RefreshCcw className="w-4 h-4" />
          Recompute All Risk Metrics
        </Button>
      </div>

      {/* Client List */}
      <div className="bg-white rounded-xl border border-slate-200 p-5">
        <div className="flex items-center gap-2 mb-4">
          <Users className="w-5 h-5 text-teal-600" />
          <h3 className="text-base font-semibold text-slate-800">Clients</h3>
        </div>

        {clientsLoading ? (
          <div className="flex justify-center py-8"><Spinner /></div>
        ) : !clients || clients.length === 0 ? (
          <p className="text-sm text-slate-400 py-4">No clients found.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-slate-50 border-b border-slate-200">
                  <th className="px-3 py-2 text-left text-xs font-semibold text-slate-400 uppercase">Name</th>
                  <th className="px-3 py-2 text-left text-xs font-semibold text-slate-400 uppercase">Username</th>
                  <th className="px-3 py-2 text-left text-xs font-semibold text-slate-400 uppercase">Code</th>
                  <th className="px-3 py-2 text-left text-xs font-semibold text-slate-400 uppercase">Status</th>
                  <th className="px-3 py-2 text-left text-xs font-semibold text-slate-400 uppercase">Last Login</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {(Array.isArray(clients) ? clients : []).map((c) => (
                  <tr key={c.id} className="hover:bg-slate-50">
                    <td className="px-3 py-2 font-medium text-slate-800">{c.name}</td>
                    <td className="px-3 py-2 text-slate-600 font-mono text-xs">{c.username}</td>
                    <td className="px-3 py-2 text-slate-600 font-mono text-xs">{c.client_code}</td>
                    <td className="px-3 py-2">
                      <Badge variant={c.is_active ? 'active' : 'inactive'}>
                        {c.is_active ? 'Active' : 'Inactive'}
                      </Badge>
                    </td>
                    <td className="px-3 py-2 text-xs text-slate-500">
                      {c.last_login ? formatDate(c.last_login) : 'Never'}
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
          <h3 className="text-base font-semibold text-slate-800">Recent Uploads</h3>
        </div>

        {logsLoading ? (
          <div className="flex justify-center py-8"><Spinner /></div>
        ) : !logs || logs.length === 0 ? (
          <p className="text-sm text-slate-400 py-4">No uploads yet.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-slate-50 border-b border-slate-200">
                  <th className="px-3 py-2 text-left text-xs font-semibold text-slate-400 uppercase">Date</th>
                  <th className="px-3 py-2 text-left text-xs font-semibold text-slate-400 uppercase">Type</th>
                  <th className="px-3 py-2 text-left text-xs font-semibold text-slate-400 uppercase">Filename</th>
                  <th className="px-3 py-2 text-right text-xs font-semibold text-slate-400 uppercase">Processed</th>
                  <th className="px-3 py-2 text-right text-xs font-semibold text-slate-400 uppercase">Failed</th>
                  <th className="px-3 py-2 text-left text-xs font-semibold text-slate-400 uppercase">Status</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {(Array.isArray(logs) ? logs : []).map((log) => (
                  <tr key={log.id} className="hover:bg-slate-50">
                    <td className="px-3 py-2 text-xs text-slate-600">{formatDate(log.uploaded_at)}</td>
                    <td className="px-3 py-2">
                      <Badge variant={log.file_type === 'nav' ? 'active' : 'pending'}>
                        {log.file_type?.toUpperCase()}
                      </Badge>
                    </td>
                    <td className="px-3 py-2 text-xs text-slate-600 font-mono truncate max-w-xs">{log.filename}</td>
                    <td className="px-3 py-2 text-right font-mono text-xs">{log.rows_processed}</td>
                    <td className="px-3 py-2 text-right font-mono text-xs text-red-600">{log.rows_failed}</td>
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
