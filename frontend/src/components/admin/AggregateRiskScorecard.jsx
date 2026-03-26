'use client';

import { useAggregateRisk } from '@/hooks/useAggregate';
import { formatPct, formatPctUnsigned } from '@/lib/format';

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
      <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
        {Array.from({ length: 12 }).map((_, i) => (
          <div key={i} className="h-20 bg-slate-100 rounded-xl" />
        ))}
      </div>
    </div>
  );
}

function MetricCard({ label, value, subtitle, description, color = 'text-slate-800' }) {
  return (
    <div className="bg-slate-50 rounded-xl p-3">
      <p className="text-xs text-slate-500 mb-1">{label}</p>
      <p className={`text-lg font-bold font-mono tabular-nums ${color}`}>
        {value}
      </p>
      {subtitle && (
        <p className="text-xs text-slate-400 mt-0.5">{subtitle}</p>
      )}
      {description && (
        <p className="text-[10px] text-slate-400 mt-1.5 leading-snug border-t border-slate-200 pt-1.5">{description}</p>
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

export default function AggregateRiskScorecard() {
  const { data, loading, error } = useAggregateRisk();

  if (loading) return <Skeleton />;
  if (error) {
    return (
      <div className="bg-white rounded-xl border border-slate-200 p-5">
        <p className="text-red-600 text-sm">Failed to load aggregate risk data: {error}</p>
      </div>
    );
  }
  if (!data) {
    return (
      <div className="bg-white rounded-xl border border-slate-200 p-5">
        <p className="text-slate-500 text-sm">No aggregate risk data available.</p>
      </div>
    );
  }

  const m = data;

  return (
    <div className="bg-white rounded-xl border border-slate-200 p-3 sm:p-5 overflow-hidden">
      <h2 className="text-lg sm:text-xl font-semibold text-slate-800 mb-4">
        Aggregate Risk Scorecard
      </h2>

      {/* Risk gauges */}
      <div className="flex flex-col sm:flex-row gap-4 sm:gap-6 mb-5">
        <RiskGauge value={m.volatility} maxValue={30} label="Volatility" />
        <RiskGauge value={Math.abs(num(m.max_drawdown))} maxValue={40} label="Max DD" />
        <RiskGauge value={m.ulcer_index} maxValue={20} label="Ulcer Index" />
      </div>

      {/* Metric cards */}
      <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
        <MetricCard
          label="Sharpe Ratio"
          value={safe(m.sharpe_ratio)}
          subtitle={num(m.sharpe_ratio) > 1 ? 'Good risk-adjusted returns' : 'Below threshold'}
          description="Excess return per unit of total risk. >1 = good, >2 = excellent."
          color={num(m.sharpe_ratio) > 1 ? 'text-emerald-600' : 'text-slate-800'}
        />
        <MetricCard
          label="Sortino Ratio"
          value={safe(m.sortino_ratio)}
          subtitle="Downside risk-adjusted"
          description="Like Sharpe but only penalizes downside volatility. Higher = better downside management."
          color={num(m.sortino_ratio) > 1 ? 'text-emerald-600' : 'text-slate-800'}
        />
        <MetricCard
          label="Max Drawdown"
          value={formatPct(m.max_drawdown)}
          subtitle={m.max_dd_start ? `${m.max_dd_start} to ${m.max_dd_end}` : undefined}
          description="Largest peak-to-trough decline. Shows worst-case loss experienced."
          color="text-red-600"
        />
        <MetricCard
          label="Beta"
          value={safe(m.beta)}
          subtitle={num(m.beta) < 1 ? 'Defensive positioning' : 'Aggressive positioning'}
          description="Sensitivity to market moves. <1 = less volatile than market, >1 = more volatile."
          color={num(m.beta) < 1 ? 'text-emerald-600' : 'text-amber-600'}
        />
        <MetricCard
          label="Alpha"
          value={formatPct(m.alpha)}
          subtitle={num(m.alpha) > 0 ? 'Excess return above market' : 'Below market-adjusted return'}
          description="Return beyond what market risk (beta) would predict. Positive = manager skill adds value."
          color={num(m.alpha) > 0 ? 'text-emerald-600' : 'text-red-600'}
        />
        <MetricCard
          label="Up Capture"
          value={formatPctUnsigned(m.up_capture, 1)}
          subtitle={num(m.up_capture) >= 100 ? 'Capturing more than market' : 'Partial market capture'}
          description="% of market gains captured on up days. >100% = outperforming in rallies."
          color={num(m.up_capture) >= 100 ? 'text-emerald-600' : 'text-slate-800'}
        />
        <MetricCard
          label="Down Capture"
          value={formatPctUnsigned(m.down_capture, 1)}
          subtitle={num(m.down_capture) < 100 ? 'Better downside protection' : 'Losing more than market'}
          description="% of market losses absorbed on down days. <100% = losing less than market in declines."
          color={num(m.down_capture) < 100 ? 'text-emerald-600' : 'text-red-600'}
        />
        <MetricCard
          label="Information Ratio"
          value={safe(m.information_ratio)}
          subtitle={num(m.information_ratio) > 0.5 ? 'Good active management' : 'Average active management'}
          description="Risk-adjusted excess return vs benchmark. >0.5 = good, >1.0 = excellent active management."
        />
        <MetricCard
          label="Tracking Error"
          value={formatPctUnsigned(m.tracking_error)}
          subtitle={num(m.tracking_error) > 10 ? 'Highly active' : 'Moderate deviation'}
          description="How much portfolio returns deviate from benchmark. Higher = more active management."
        />
        <MetricCard
          label="Ulcer Index"
          value={safe(m.ulcer_index)}
          subtitle={num(m.ulcer_index) < 5 ? 'Low stress' : num(m.ulcer_index) < 10 ? 'Moderate stress' : 'High stress'}
          description="Measures depth and duration of all drawdowns. 0-5 = low stress, 10+ = high stress."
          color={num(m.ulcer_index) < 5 ? 'text-emerald-600' : num(m.ulcer_index) < 10 ? 'text-amber-600' : 'text-red-600'}
        />
        <MetricCard
          label="Monthly Hit Rate"
          value={formatPctUnsigned(m.monthly_hit_rate, 1)}
          subtitle={`${num(m.win_months || m.win_count)} wins / ${num(m.loss_months || m.loss_count)} losses`}
          description="% of months with positive returns. Higher = more consistent performance."
          color={num(m.monthly_hit_rate) > 50 ? 'text-emerald-600' : 'text-red-600'}
        />
        <MetricCard
          label="Market Correlation"
          value={safe(m.market_correlation)}
          subtitle={num(m.market_correlation) < 0.7 ? 'Independent sources' : 'Tracks market closely'}
          description="How closely portfolio moves with the market. <0.7 = meaningful independent returns."
        />
      </div>
    </div>
  );
}
