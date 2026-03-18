'use client';

import { useSummary } from '@/hooks/usePortfolio';
import { formatINRShort, formatPct, pnlColor } from '@/lib/format';
import {
  Wallet,
  TrendingUp,
  BarChart3,
  Target,
  Calendar,
  ShieldAlert,
} from 'lucide-react';

const SKELETON_PULSE = 'animate-pulse bg-slate-200 rounded';

function SkeletonCard() {
  return (
    <div className="bg-white rounded-xl border border-slate-200 p-5">
      <div className={`${SKELETON_PULSE} h-4 w-20 mb-3`} />
      <div className={`${SKELETON_PULSE} h-8 w-32 mb-2`} />
      <div className={`${SKELETON_PULSE} h-3 w-16`} />
    </div>
  );
}

function StatCard({ icon: Icon, label, value, subtitle, valueColor, iconColor }) {
  return (
    <div className="bg-white rounded-xl border border-slate-200 p-3 sm:p-5">
      <div className="flex items-center justify-between mb-2">
        <p className="text-xs sm:text-sm text-slate-500">{label}</p>
        <div className={`p-1.5 sm:p-2 rounded-lg ${iconColor || 'bg-slate-100'}`}>
          <Icon className="w-3.5 h-3.5 sm:w-4 sm:h-4 text-slate-600" />
        </div>
      </div>
      <p className={`text-xl sm:text-2xl font-bold font-mono tabular-nums ${valueColor || 'text-slate-800'}`}>
        {value}
      </p>
      {subtitle && (
        <p className="text-xs text-slate-400 mt-1">{subtitle}</p>
      )}
    </div>
  );
}

export default function SummaryCards() {
  const { data, loading, error } = useSummary();

  if (loading) {
    return (
      <div className="grid grid-cols-2 sm:grid-cols-2 lg:grid-cols-3 gap-3 sm:gap-4">
        {Array.from({ length: 6 }).map((_, i) => (
          <SkeletonCard key={i} />
        ))}
      </div>
    );
  }

  if (error) {
    return (
      <div className="bg-red-50 border border-red-200 rounded-xl p-5 text-red-600 text-sm">
        Failed to load summary: {error}
      </div>
    );
  }

  if (!data) return null;

  const profitColor = pnlColor(data.profit_amount);
  const cagrColor = pnlColor(data.cagr);
  const ytdColor = pnlColor(data.ytd_return);

  const cards = [
    {
      icon: Wallet,
      label: 'Total Invested',
      value: formatINRShort(data.invested),
      subtitle: 'Corpus',
      iconColor: 'bg-slate-100',
      valueColor: 'text-slate-800',
    },
    {
      icon: TrendingUp,
      label: 'Current Value',
      value: formatINRShort(data.current_value),
      subtitle: `As of ${data.as_of_date || '--'}`,
      iconColor: 'bg-teal-50',
      valueColor: 'text-jip-teal',
    },
    {
      icon: BarChart3,
      label: 'Profit / Loss',
      value: formatINRShort(data.profit_amount),
      subtitle: formatPct(data.profit_pct),
      iconColor: Number(data.profit_amount) >= 0 ? 'bg-emerald-50' : 'bg-red-50',
      valueColor: profitColor,
    },
    {
      icon: Target,
      label: 'CAGR',
      value: formatPct(data.cagr),
      subtitle: 'Since inception',
      iconColor: 'bg-teal-50',
      valueColor: cagrColor,
    },
    {
      icon: Calendar,
      label: 'YTD Return',
      value: formatPct(data.ytd_return),
      subtitle: 'Calendar year',
      iconColor: 'bg-blue-50',
      valueColor: ytdColor,
    },
    {
      icon: ShieldAlert,
      label: 'Max Drawdown',
      value: formatPct(data.max_drawdown),
      subtitle: 'Peak to trough',
      iconColor: 'bg-red-50',
      valueColor: 'text-red-600',
    },
  ];

  return (
    <div className="grid grid-cols-2 sm:grid-cols-2 lg:grid-cols-3 gap-3 sm:gap-4">
      {cards.map((card) => (
        <StatCard key={card.label} {...card} />
      ))}
    </div>
  );
}
