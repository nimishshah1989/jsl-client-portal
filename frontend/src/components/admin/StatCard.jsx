'use client';

const COLOR_MAP = {
  teal: 'text-teal-600 bg-teal-50',
  emerald: 'text-emerald-600 bg-emerald-50',
  red: 'text-red-600 bg-red-50',
  amber: 'text-amber-600 bg-amber-50',
  slate: 'text-slate-600 bg-slate-100',
  blue: 'text-blue-600 bg-blue-50',
};

export default function StatCard({ label, value, subtitle, icon: Icon, color = 'teal' }) {
  const iconClasses = COLOR_MAP[color] || COLOR_MAP.teal;

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
