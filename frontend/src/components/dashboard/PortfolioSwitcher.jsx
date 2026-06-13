'use client';

import { usePortfolioSelection } from '@/hooks/usePortfolioSelection';

const STRATEGY_LABEL = { LEADERS: 'Leaders', PASSIVE: 'Passive', IND11: 'IND11' };

/**
 * Portfolio switcher: Combined (default) + one button per portfolio.
 * Hidden for single-portfolio clients (Combined == their only portfolio).
 * Closed portfolios are selectable (to view their history) but marked.
 */
export default function PortfolioSwitcher() {
  const { selection, setSelection, portfolios } = usePortfolioSelection();

  if (!portfolios || portfolios.length <= 1) return null;

  const options = [
    { key: 'COMBINED', label: 'Combined' },
    ...portfolios.map((p) => ({
      key: p.portfolio_id,
      label:
        `${STRATEGY_LABEL[p.strategy] || p.strategy}` +
        (p.client_code ? ` · ${p.client_code}` : '') +
        (p.is_closed ? ' (closed)' : ''),
    })),
  ];

  return (
    <div className="bg-white rounded-xl border border-slate-200 p-3 mb-4 sm:mb-6 flex flex-wrap items-center gap-2">
      <span className="text-xs font-semibold text-slate-500 uppercase tracking-wider mr-1">
        Portfolio
      </span>
      {options.map((o) => (
        <button
          key={o.key}
          onClick={() => setSelection(o.key)}
          className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${
            selection === o.key
              ? 'bg-jip-teal text-white'
              : 'bg-slate-100 text-slate-600 hover:bg-slate-200'
          }`}
        >
          {o.label}
        </button>
      ))}
      <span className="text-xs text-slate-400 ml-auto">
        Combined sums your live portfolios (closed excluded)
      </span>
    </div>
  );
}
