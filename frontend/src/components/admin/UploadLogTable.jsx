'use client';

import { formatDate } from '@/lib/format';
import Badge from '@/components/ui/Badge';
import Spinner from '@/components/ui/Spinner';
import { Upload, AlertCircle } from 'lucide-react';

export default function UploadLogTable({ logs, loading }) {
  return (
    <div className="bg-white rounded-xl border border-slate-200 p-5">
      <div className="flex items-center gap-2 mb-4">
        <Upload className="w-5 h-5 text-teal-600" />
        <h3 className="text-base font-semibold text-slate-800">
          Recent Uploads
        </h3>
      </div>

      {loading ? (
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
  );
}
