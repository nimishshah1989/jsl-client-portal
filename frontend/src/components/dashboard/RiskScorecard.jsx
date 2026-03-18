'use client';

import { useRiskScorecard } from '@/hooks/usePortfolio';
import { formatPct, formatPctUnsigned } from '@/lib/format';

/** Safely convert to number, return fallback if null/NaN */
function num(v, fallback = 0) {
  if (v == null || v === '') return fallback;
  const n = Number(v);
  return isNaN(n) ? fallback : n;
}

function safe(v, decimals = 2) {
  const n = num(v, null);
  return n != null ? n.toFixed(decimals) : '--';
}

function Skeleton() {
  return (
    <div className="bg-white rounded-xl border border-slate-200 p-5 animate-pulse">
      <div className="h-5 w-52 bg-slate-200 rounded mb-4" />
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        {Array.from({ length: 8 }).map((_, i) => (
          <div key={i} className="h-24 bg-slate-100 rounded-xl" />
        ))}
      </div>
    </div>
  );
}

function MetricCard({ label, value, subtitle, explanation, color = 'text-slate-800' }) {
  return (
    <div className="bg-slate-50 rounded-xl p-4">
      <p className="text-xs text-slate-500 mb-1">{label}</p>
      <p className={`text-lg font-bold font-mono tabular-nums ${color}`}>
        {value}
      </p>
      {subtitle && (
        <p className="text-xs text-slate-400 mt-0.5">{subtitle}</p>
      )}
      {explanation && (
        <p className="text-[11px] text-slate-400 mt-1.5 leading-tight">{explanation}</p>
      )}
    </div>
  );
}

function RiskGauge({ value, maxValue = 30, label }) {
  const v = num(value);
  const pct = Math.min(100, Math.max(0, (Math.abs(v) / maxValue) * 100));
  const getColor = () => {
    if (pct < 33) return 'bg-emerald-500';
    if (pct < 66) return 'bg-amber-500';
    return 'bg-red-500';
  };

  return (
    <div className="flex-1">
      <div className="flex justify-between items-end mb-1">
        <span className="text-xs text-slate-500">{label}</span>
        <span className="text-sm font-mono font-bold text-slate-800">{v.toFixed(2)}</span>
      </div>
      <div className="h-2 bg-slate-200 rounded-full overflow-hidden">
        <div
          className={`h-full rounded-full transition-all ${getColor()}`}
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}

export default function RiskScorecard() {
  const { data, loading, error } = useRiskScorecard();

  if (loading) return <Skeleton />;
  if (error) {
    return (
      <div className="bg-white rounded-xl border border-slate-200 p-5">
        <p className="text-red-600 text-sm">Failed to load risk data: {error}</p>
      </div>
    );
  }
  if (!data) {
    return (
      <div className="bg-white rounded-xl border border-slate-200 p-5">
        <p className="text-slate-500 text-sm">No risk data available.</p>
      </div>
    );
  }

  const m = data;

  return (
    <div className="bg-white rounded-xl border border-slate-200 p-3 sm:p-5 overflow-hidden">
      <h2 className="text-lg sm:text-xl font-semibold text-slate-800 mb-4">
        Risk Management Scorecard
      </h2>

      {/* Risk gauges */}
      <div className="flex flex-col sm:flex-row gap-4 sm:gap-6 mb-6">
        <RiskGauge value={m.volatility} maxValue={30} label="Volatility" />
        <RiskGauge value={Math.abs(num(m.max_drawdown))} maxValue={40} label="Max DD" />
        <RiskGauge value={m.ulcer_index} maxValue={20} label="Ulcer Index" />
      </div>

      {/* Metric cards grid */}
      <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-4 gap-3">
        <MetricCard
          label="Up Capture"
          value={formatPctUnsigned(m.up_capture, 1)}
          subtitle={num(m.up_capture) >= 100 ? 'Capturing more than market gains' : 'Capturing less than market gains'}
          explanation="% of benchmark gains captured on up days. >100% = outperforming on rallies."
          color={num(m.up_capture) >= 100 ? 'text-emerald-600' : 'text-slate-800'}
        />
        <MetricCard
          label="Down Capture"
          value={formatPctUnsigned(m.down_capture, 1)}
          subtitle={num(m.down_capture) < 100 ? 'Losing less than market on down days' : 'Losing more than market on down days'}
          explanation="% of benchmark losses absorbed on down days. <100% = better downside protection."
          color={num(m.down_capture) < 100 ? 'text-emerald-600' : 'text-red-600'}
        />
        <MetricCard
          label="Beta"
          value={safe(m.beta)}
          subtitle={num(m.beta) < 1 ? `Defensive (${safe(m.beta)}x market sensitivity)` : `Aggressive (${safe(m.beta)}x market sensitivity)`}
          explanation="Sensitivity to market moves. <1 = less volatile than market, >1 = more volatile."
          color={num(m.beta) < 1 ? 'text-emerald-600' : 'text-amber-600'}
        />
        <MetricCard
          label="Alpha"
          value={formatPct(m.alpha)}
          subtitle={num(m.alpha) > 0 ? 'Excess return above market risk' : 'Underperforming vs market risk'}
          explanation="Return beyond what beta-adjusted market exposure would predict. Positive = manager skill adds value."
          color={num(m.alpha) > 0 ? 'text-emerald-600' : 'text-red-600'}
        />
        <MetricCard
          label="Information Ratio"
          value={safe(m.information_ratio)}
          subtitle={num(m.information_ratio) > 1 ? 'Excellent active mgmt' : num(m.information_ratio) > 0.5 ? 'Good active mgmt' : 'Average active mgmt'}
          explanation="Risk-adjusted excess return vs benchmark. >0.5 = good, >1.0 = excellent."
        />
        <MetricCard
          label="Tracking Error"
          value={formatPctUnsigned(m.tracking_error)}
          subtitle={num(m.tracking_error) > 10 ? 'Highly active strategy' : 'Moderate active deviation'}
          explanation="How much the portfolio deviates from the benchmark. Higher = more active management."
        />
        <MetricCard
          label="Max Consec. Loss"
          value={`${num(m.max_consecutive_loss)} months`}
          subtitle={num(m.max_consecutive_loss) <= 2 ? 'Within normal range' : num(m.max_consecutive_loss) <= 4 ? 'Notable losing streak' : 'Extended downturn period'}
          explanation="Longest unbroken run of negative monthly returns. Tests investor patience."
          color={num(m.max_consecutive_loss) > 3 ? 'text-red-600' : 'text-slate-800'}
        />
        <MetricCard
          label="Market Correlation"
          value={safe(m.market_correlation)}
          subtitle={num(m.market_correlation) < 0.7 ? 'Independent return sources' : 'Closely tracks market'}
          explanation="Pearson correlation with NIFTY 50 daily returns. <0.7 = meaningful diversification."
        />
      </div>

      {/* Cash metrics row */}
      <div className="mt-4 grid grid-cols-1 sm:grid-cols-3 gap-3">
        <MetricCard
          label="Current Cash"
          value={formatPctUnsigned(m.current_cash, 1)}
          subtitle="Cash + liquid funds as of latest NAV"
          explanation="Current allocation to cash and liquid fund equivalents."
        />
        <MetricCard
          label="Avg Cash Held"
          value={formatPctUnsigned(m.avg_cash_held, 1)}
          subtitle="Average defensive positioning since inception"
          explanation="Higher avg cash = more conservative approach over time."
        />
        <MetricCard
          label="Max Cash Held"
          value={formatPctUnsigned(m.max_cash_held, 1)}
          subtitle="Peak defensive position ever taken"
          explanation="Shows willingness to go heavily into cash during risky markets."
        />
      </div>
    </div>
  );
}
