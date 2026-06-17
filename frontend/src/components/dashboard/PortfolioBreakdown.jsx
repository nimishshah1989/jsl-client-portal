'use client';

import { usePortfoliosSummary } from '@/hooks/usePortfolio';
import { usePortfolioSelection } from '@/hooks/usePortfolioSelection';
import { formatINRShort, formatPct, pnlColor } from '@/lib/format';

const STRATEGY_LABEL = {
  LEADERS: 'Leaders',
  PASSIVE: 'Passive',
  IND11: 'IND11',
};

/**
 * "Your Portfolios" — a one-glance table of all the client's live sleeves with
 * key metrics, plus a Combined total row. Only shown on the Combined view and
 * only when the client holds more than one live portfolio (otherwise the
 * Combined view already equals that single portfolio).
 */
export default function PortfolioBreakdown() {
  const { selection, portfolios } = usePortfolioSelection();
  const { data, loading } = usePortfoliosSummary();

  const liveCount = (portfolios || []).filter((p) => !p.is_closed).length;
  if (selection !== 'COMBINED' || liveCount < 2) return null;

  const rows = data?.portfolios || [];
  const combined = data?.combined || {};
  if (loading || rows.length === 0) return null;

  const th = 'px-3 py-2.5 text-xs font-semibold text-slate-400 uppercase tracking-wider whitespace-nowrap';
  const tdNum = 'px-3 py-2.5 text-right font-mono tabular-nums text-xs';

  return (
    <div className="bg-white rounded-xl border border-slate-200 p-3 sm:p-5 overflow-hidden">
      <div className="mb-4">
        <h2 className="text-lg sm:text-xl font-semibold text-slate-800">Your Portfolios</h2>
        <p className="text-xs text-slate-400 mt-0.5">
          All your portfolios at a glance · Return is absolute, CAGR is annualised
        </p>
      </div>

      <div className="overflow-x-auto" style={{ WebkitOverflowScrolling: 'touch' }}>
        <table className="min-w-[600px] w-full text-sm">
          <thead>
            <tr className="bg-slate-50 border-b border-slate-200">
              <th className={`${th} text-left`}>Portfolio</th>
              <th className={`${th} text-right`}>Invested</th>
              <th className={`${th} text-right`}>Current</th>
              <th className={`${th} text-right`}>Return</th>
              <th className={`${th} text-right`}>CAGR</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {rows.map((p) => (
              <tr key={p.client_code} className="hover:bg-slate-50 transition-colors">
                <td className="px-3 py-2.5">
                  <p className="font-medium text-slate-800 text-xs">
                    {STRATEGY_LABEL[p.strategy] || p.strategy || 'Portfolio'}
                  </p>
                  {p.client_code && (
                    <p className="text-xs text-slate-400 font-mono">{p.client_code}</p>
                  )}
                </td>
                <td className={`${tdNum} text-slate-700`}>{formatINRShort(p.invested)}</td>
                <td className={`${tdNum} font-medium text-slate-800`}>{formatINRShort(p.current_value)}</td>
                <td className={`${tdNum} ${pnlColor(p.return_pct)}`}>{formatPct(p.return_pct)}</td>
                <td className={`${tdNum} ${p.cagr != null ? pnlColor(p.cagr) : 'text-slate-400'}`}>
                  {p.cagr != null ? formatPct(p.cagr) : '--'}
                </td>
              </tr>
            ))}
          </tbody>
          <tfoot>
            <tr className="bg-slate-50 border-t-2 border-slate-300">
              <td className="px-3 py-2.5 text-xs font-semibold text-slate-700">
                Combined ({rows.length} portfolios)
              </td>
              <td className={`${tdNum} font-semibold text-slate-700`}>{formatINRShort(combined.invested)}</td>
              <td className={`${tdNum} font-semibold text-slate-800`}>{formatINRShort(combined.current_value)}</td>
              <td className={`${tdNum} font-semibold ${pnlColor(combined.profit_pct)}`}>{formatPct(combined.profit_pct)}</td>
              <td className={`${tdNum} font-semibold ${combined.cagr != null ? pnlColor(combined.cagr) : 'text-slate-400'}`}>
                {combined.cagr != null ? formatPct(combined.cagr) : '--'}
              </td>
            </tr>
          </tfoot>
        </table>
      </div>
    </div>
  );
}
