'use client';

import { formatPct, formatINRShort, pnlColor } from '@/lib/format';

export default function PerformerTable({
  title,
  performers,
  icon: Icon,
  valueKey = 'cagr',
  valueFormat = 'pct',
  subtitleKey = 'aum',
}) {
  if (!performers || performers.length === 0) {
    return null;
  }

  function formatValue(p) {
    const val = p[valueKey];
    if (valueFormat === 'pct') return formatPct(val);
    return formatINRShort(val);
  }

  function valueColor(p) {
    if (valueFormat === 'pct') return pnlColor(p[valueKey]);
    return 'text-slate-800';
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
              <p className={`text-sm font-bold font-mono ${valueColor(p)}`}>
                {formatValue(p)}
              </p>
              {subtitleKey && (
                <p className="text-xs text-slate-400 font-mono">
                  {formatINRShort(p[subtitleKey])}
                </p>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
