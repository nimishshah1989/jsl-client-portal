'use client';

import { formatDate } from '@/lib/format';
import Badge from '@/components/ui/Badge';
import Spinner from '@/components/ui/Spinner';
import { Users, Eye } from 'lucide-react';

export default function ClientListTable({ clients, loading, impersonating, onViewClient }) {
  return (
    <div className="bg-white rounded-xl border border-slate-200 p-5">
      <div className="flex items-center gap-2 mb-4">
        <Users className="w-5 h-5 text-teal-600" />
        <h3 className="text-base font-semibold text-slate-800">Clients</h3>
        <span className="text-xs text-slate-400 ml-1">
          (click to view portfolio)
        </span>
      </div>

      {loading ? (
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
                  onClick={() => !c.is_admin && onViewClient(c.id)}
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
                          onViewClient(c.id);
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
  );
}
