'use client';

import { useState } from 'react';
import { useMethodology } from '@/hooks/usePortfolio';
import { formatPct, formatDate } from '@/lib/format';
import Spinner from '@/components/ui/Spinner';
import { ChevronDown, ChevronRight, Calculator } from 'lucide-react';

/**
 * Accordion item for a single metric.
 */
function AccordionItem({ title, value, children }) {
  const [open, setOpen] = useState(false);

  return (
    <div className="border border-slate-200 rounded-xl overflow-hidden">
      <button
        onClick={() => setOpen(!open)}
        className="w-full flex items-center justify-between px-5 py-4 bg-white hover:bg-slate-50 transition-colors text-left"
      >
        <div className="flex items-center gap-3">
          {open ? (
            <ChevronDown className="w-4 h-4 text-teal-600 shrink-0" />
          ) : (
            <ChevronRight className="w-4 h-4 text-slate-400 shrink-0" />
          )}
          <span className="font-semibold text-slate-800">{title}</span>
        </div>
        {value != null && (
          <span className="font-mono tabular-nums text-teal-600 font-medium text-sm">
            {typeof value === 'number' ? formatPct(value) : value}
          </span>
        )}
      </button>
      {open && (
        <div className="px-5 pb-5 pt-2 border-t border-slate-100 bg-white">
          <div className="space-y-4 text-sm text-slate-600">
            {children}
          </div>
        </div>
      )}
    </div>
  );
}

/**
 * Section header for grouping metrics.
 */
function SectionHeader({ title }) {
  return (
    <h3 className="text-base font-semibold text-slate-800 mt-6 mb-3 first:mt-0">{title}</h3>
  );
}

/**
 * Formula display block.
 */
function Formula({ children }) {
  return (
    <div className="bg-slate-50 rounded-lg p-4 font-mono text-sm text-slate-700">
      {children}
    </div>
  );
}

/**
 * Worked example block with client's actual numbers.
 */
function WorkedExample({ children }) {
  return (
    <div className="bg-slate-50 rounded-lg p-4">
      <p className="font-medium text-slate-700 mb-2">Your numbers:</p>
      {children}
    </div>
  );
}

/**
 * Interpretation note.
 */
function Interpretation({ children }) {
  return (
    <div className="text-xs text-slate-500">
      {children}
    </div>
  );
}

export default function MethodologyPage() {
  const { data, loading, error } = useMethodology();

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <Spinner size="lg" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="bg-red-50 border border-red-200 rounded-xl p-5 text-red-600 text-sm">
        Failed to load methodology data: {error}
      </div>
    );
  }

  const m = data?.metrics || {};
  const rfr = data?.risk_free_rate || 6.50;
  const benchmark = data?.benchmark_name || 'NIFTY 50';
  const asOf = data?.as_of_date;

  // Helper to safely get metric values
  function mv(key) {
    return m[key]?.value;
  }

  function mi(key, input) {
    return m[key]?.inputs?.[input];
  }

  function mb(key) {
    return m[key]?.benchmark_value;
  }

  return (
    <div className="max-w-3xl mx-auto">
      {/* Header */}
      <div className="flex items-center gap-3 mb-2">
        <div className="p-2.5 bg-teal-50 rounded-xl">
          <Calculator className="w-6 h-6 text-teal-600" />
        </div>
        <div>
          <h1 className="text-2xl font-bold text-slate-800">Calculation Methodology</h1>
          <p className="text-sm text-slate-500">
            How every number on your dashboard is computed
          </p>
        </div>
      </div>
      {asOf && (
        <p className="text-xs text-slate-400 mb-6">
          Data as of {formatDate(asOf)} | Risk-free rate: {rfr}% | Benchmark: {benchmark}
        </p>
      )}

      {/* Portfolio Returns */}
      <SectionHeader title="Portfolio Returns" />
      <div className="space-y-3">
        <AccordionItem title="Absolute Return" value={mv('absolute_return')}>
          <p>
            The simple total return over a period, not annualized.
            Shows how much your portfolio gained or lost in percentage terms.
          </p>
          <Formula>Absolute Return = (NAV_end / NAV_start) - 1</Formula>
          <WorkedExample>
            <p>NAV at period start = {mi('absolute_return', 'start_nav')?.toFixed(2) || '--'}</p>
            <p>NAV at period end = {mi('absolute_return', 'end_nav')?.toFixed(2) || '--'}</p>
            <p className="mt-2 font-semibold text-slate-800">
              = ({mi('absolute_return', 'end_nav')?.toFixed(2) || '--'} / {mi('absolute_return', 'start_nav')?.toFixed(2) || '--'}) - 1
              = <span className="text-teal-600">{formatPct(mv('absolute_return'))}</span>
            </p>
          </WorkedExample>
        </AccordionItem>

        <AccordionItem title="CAGR (Compound Annual Growth Rate)" value={mv('cagr')}>
          <p>
            The annualized rate of return, smoothing out volatility. Shows what constant
            annual return would have produced the same total return over the period.
          </p>
          <Formula>
            {'CAGR = ((End Value / Start Value) ^ (365.25 / Days)) - 1'}
          </Formula>
          <WorkedExample>
            <p>Start Value = {mi('cagr', 'start_value')?.toFixed(2) || '--'}</p>
            <p>End Value = {mi('cagr', 'end_value')?.toFixed(2) || '--'}</p>
            <p>Days = {mi('cagr', 'days') || '--'}</p>
            <p className="mt-2 font-semibold text-slate-800">
              = <span className="text-teal-600">{formatPct(mv('cagr'))}</span>
            </p>
          </WorkedExample>
          <Interpretation>
            <p>Uses 365.25 days/year to account for leap years.</p>
            <p>Benchmark ({benchmark}) CAGR: {mb('cagr') != null ? formatPct(mb('cagr')) : '--'}</p>
          </Interpretation>
        </AccordionItem>

        <AccordionItem title="XIRR (Extended Internal Rate of Return)" value={mv('xirr')}>
          <p>
            Your personalized return accounting for the exact timing and amount of each
            investment you made. Unlike CAGR, XIRR reflects when you actually put money in.
          </p>
          <Formula>
            {'XIRR: Find rate r where Sum(CF_i / (1+r)^((date_i - date_0)/365)) = 0'}
          </Formula>
          <WorkedExample>
            <p>Number of cash flows: {mi('xirr', 'num_cash_flows') || '--'}</p>
            <p>First investment date: {mi('xirr', 'first_date') || '--'}</p>
            <p>Total invested: {mi('xirr', 'total_invested') || '--'}</p>
            <p className="mt-2 font-semibold text-slate-800">
              = <span className="text-teal-600">{formatPct(mv('xirr'))}</span>
            </p>
          </WorkedExample>
          <Interpretation>
            <p>Solved numerically using Brent's method (scipy.optimize.brentq).</p>
          </Interpretation>
        </AccordionItem>
      </div>

      {/* Risk Metrics */}
      <SectionHeader title="Risk Metrics" />
      <div className="space-y-3">
        <AccordionItem title="Volatility (Annualized)" value={mv('volatility')}>
          <p>
            Measures the dispersion of daily returns. Higher volatility means more
            unpredictable day-to-day price changes. Annualized by multiplying by the
            square root of 252 trading days.
          </p>
          <Formula>Volatility = Std Dev(daily returns) x sqrt(252)</Formula>
          <WorkedExample>
            <p>Daily return std dev = {mi('volatility', 'daily_std')?.toFixed(4) || '--'}</p>
            <p className="mt-2 font-semibold text-slate-800">
              = {mi('volatility', 'daily_std')?.toFixed(4) || '--'} x {Math.sqrt(252).toFixed(2)}
              = <span className="text-teal-600">{formatPct(mv('volatility'))}</span>
            </p>
          </WorkedExample>
          <Interpretation>
            <p>Benchmark ({benchmark}) Volatility: {mb('volatility') != null ? formatPct(mb('volatility')) : '--'}</p>
          </Interpretation>
        </AccordionItem>

        <AccordionItem title="Maximum Drawdown" value={mv('max_drawdown')}>
          <p>
            The largest peak-to-trough decline in portfolio value. Shows the worst
            loss you would have experienced at any point during the investment period.
          </p>
          <Formula>Max DD = max((Peak_t - NAV_t) / Peak_t) for all t</Formula>
          <WorkedExample>
            <p>Peak date: {mi('max_drawdown', 'dd_start') || '--'}</p>
            <p>Trough date: {mi('max_drawdown', 'dd_end') || '--'}</p>
            <p>Recovery date: {mi('max_drawdown', 'dd_recovery') || 'Not yet recovered'}</p>
            <p className="mt-2 font-semibold text-slate-800">
              = <span className="text-red-600">{formatPct(mv('max_drawdown'))}</span>
            </p>
          </WorkedExample>
        </AccordionItem>

        <AccordionItem title="Sharpe Ratio" value={mv('sharpe_ratio') != null ? mv('sharpe_ratio').toFixed(2) : '--'}>
          <p>
            Measures how much excess return you receive for each unit of risk (volatility) taken.
            It tells you whether the returns are coming from smart investment decisions or from
            taking excessive risk.
          </p>
          <Formula>Sharpe Ratio = (Portfolio CAGR - Risk-Free Rate) / Portfolio Volatility</Formula>
          <WorkedExample>
            <p>Portfolio CAGR = {formatPct(mi('sharpe_ratio', 'portfolio_cagr'))}</p>
            <p>Risk-Free Rate = {rfr}% (India 10Y Govt Bond)</p>
            <p>Portfolio Volatility = {formatPct(mi('sharpe_ratio', 'portfolio_volatility'))}</p>
            <p className="mt-2 font-semibold text-slate-800">
              = ({mi('sharpe_ratio', 'portfolio_cagr')?.toFixed(2) || '--'} - {rfr}) / {mi('sharpe_ratio', 'portfolio_volatility')?.toFixed(2) || '--'}
              = <span className="text-teal-600">{mv('sharpe_ratio')?.toFixed(2) || '--'}</span>
            </p>
          </WorkedExample>
          <Interpretation>
            <p>{'> 1.0 = Good | > 2.0 = Excellent | < 0 = Below risk-free rate'}</p>
            <p>Benchmark ({benchmark}) Sharpe: {mb('sharpe_ratio')?.toFixed(2) || '--'}</p>
          </Interpretation>
        </AccordionItem>

        <AccordionItem title="Sortino Ratio" value={mv('sortino_ratio') != null ? mv('sortino_ratio').toFixed(2) : '--'}>
          <p>
            Like the Sharpe Ratio, but only penalizes downside volatility. Upside volatility
            (good gains) does not count against you. More appropriate for portfolios with
            asymmetric returns.
          </p>
          <Formula>Sortino = (Portfolio CAGR - Risk-Free Rate) / Downside Deviation</Formula>
          <WorkedExample>
            <p>Portfolio CAGR = {formatPct(mi('sortino_ratio', 'portfolio_cagr'))}</p>
            <p>Risk-Free Rate = {rfr}%</p>
            <p>Downside Deviation = {formatPct(mi('sortino_ratio', 'downside_dev'))}</p>
            <p className="mt-2 font-semibold text-slate-800">
              = <span className="text-teal-600">{mv('sortino_ratio')?.toFixed(2) || '--'}</span>
            </p>
          </WorkedExample>
        </AccordionItem>
      </div>

      {/* Benchmark Comparison */}
      <SectionHeader title="Benchmark Comparison" />
      <div className="space-y-3">
        <AccordionItem title="Alpha (Jensen's Alpha)" value={mv('alpha')}>
          <p>
            Excess return beyond what the portfolio's market risk (beta) would predict.
            Positive alpha means the manager/strategy adds value above pure market exposure.
          </p>
          <Formula>{'Alpha = R_p - [R_f + Beta x (R_b - R_f)]'}</Formula>
          <WorkedExample>
            <p>Portfolio CAGR (R_p) = {formatPct(mi('alpha', 'port_cagr'))}</p>
            <p>Benchmark CAGR (R_b) = {formatPct(mi('alpha', 'bench_cagr'))}</p>
            <p>Beta = {mi('alpha', 'beta')?.toFixed(2) || '--'}</p>
            <p>Risk-Free Rate = {rfr}%</p>
            <p className="mt-2 font-semibold text-slate-800">
              = <span className="text-teal-600">{formatPct(mv('alpha'))}</span>
            </p>
          </WorkedExample>
        </AccordionItem>

        <AccordionItem title="Beta" value={mv('beta') != null ? mv('beta').toFixed(2) : '--'}>
          <p>
            Measures portfolio sensitivity to market movements. A beta of 1.0 means the
            portfolio moves exactly with the market. Below 1.0 means less volatile (defensive).
          </p>
          <Formula>{'Beta = Cov(R_p, R_b) / Var(R_b)'}</Formula>
          <Interpretation>
            <p>{'Beta = 1.0: moves with market | < 1.0: defensive | > 1.0: aggressive'}</p>
          </Interpretation>
        </AccordionItem>

        <AccordionItem title="Information Ratio" value={mv('information_ratio') != null ? mv('information_ratio').toFixed(2) : '--'}>
          <p>
            Measures risk-adjusted excess return over the benchmark, normalized by
            tracking error. Shows how consistently the portfolio outperforms.
          </p>
          <Formula>{'IR = (R_p - R_b) / Tracking Error'}</Formula>
          <Interpretation>
            <p>{'> 0.5 = Good active management | > 1.0 = Excellent'}</p>
          </Interpretation>
        </AccordionItem>

        <AccordionItem title="Tracking Error" value={mv('tracking_error')}>
          <p>
            Annualized standard deviation of the difference between portfolio and benchmark
            returns. Low tracking error means the portfolio closely tracks the benchmark.
          </p>
          <Formula>{'TE = StdDev(R_p - R_b) x sqrt(252)'}</Formula>
        </AccordionItem>

        <AccordionItem title="Up Capture Ratio" value={mv('up_capture')}>
          <p>
            What percentage of the benchmark's gains the portfolio captures on up days.
            Above 100% means the portfolio gains more than the market when it rises.
          </p>
          <Formula>Up Capture = Mean(port returns on UP days) / Mean(bench returns on UP days) x 100</Formula>
        </AccordionItem>

        <AccordionItem title="Down Capture Ratio" value={mv('down_capture')}>
          <p>
            What percentage of the benchmark's losses the portfolio absorbs on down days.
            Below 100% means the portfolio loses less than the market when it falls.
          </p>
          <Formula>Down Capture = Mean(port returns on DOWN days) / Mean(bench returns on DOWN days) x 100</Formula>
          <Interpretation>
            <p>Ideal: Low down capture + reasonable up capture = asymmetric returns.</p>
          </Interpretation>
        </AccordionItem>
      </div>

      {/* Drawdown & Stress */}
      <SectionHeader title="Drawdown & Stress" />
      <div className="space-y-3">
        <AccordionItem title="Ulcer Index" value={mv('ulcer_index') != null ? mv('ulcer_index').toFixed(2) : '--'}>
          <p>
            Unlike Max Drawdown which shows only the worst decline, Ulcer Index measures the
            depth and duration of ALL drawdowns via their root-mean-square. It reflects the
            ongoing stress of holding the portfolio.
          </p>
          <Formula>{'UI = sqrt(mean(DD_i^2))'}</Formula>
          <Interpretation>
            <p>0-2: Very low stress | 2-5: Low | 5-10: Moderate | 10-20: High | 20+: Severe</p>
          </Interpretation>
        </AccordionItem>

        <AccordionItem title="Maximum Consecutive Loss" value={`${mv('max_consecutive_loss') || 0} months`}>
          <p>
            The longest streak of consecutive months with negative returns.
            Shorter streaks indicate better consistency.
          </p>
        </AccordionItem>

        <AccordionItem title="Average Cash Held" value={mv('avg_cash_held') != null ? formatPct(mv('avg_cash_held'), 1) : '--'}>
          <p>
            Average cash and liquid fund allocation as a percentage of NAV across all days.
            Higher average cash indicates a more defensive positioning.
          </p>
        </AccordionItem>

        <AccordionItem title="Maximum Cash Held" value={mv('max_cash_held') != null ? formatPct(mv('max_cash_held'), 1) : '--'}>
          <p>
            Peak defensive positioning — the highest percentage of portfolio held in cash
            on any single day. Shows willingness to go heavily defensive during market stress.
          </p>
        </AccordionItem>
      </div>

      {/* Monthly Return Profile */}
      <SectionHeader title="Monthly Return Profile" />
      <div className="space-y-3">
        <AccordionItem title="Monthly Hit Rate" value={mv('monthly_hit_rate') != null ? formatPct(mv('monthly_hit_rate'), 1) : '--'}>
          <p>
            Percentage of months with positive returns. A hit rate above 60% indicates
            consistent positive performance.
          </p>
          <Formula>Hit Rate = Positive months / Total months x 100</Formula>
        </AccordionItem>

        <AccordionItem title="Market Correlation" value={mv('market_correlation') != null ? mv('market_correlation').toFixed(2) : '--'}>
          <p>
            Pearson correlation coefficient between daily portfolio and benchmark returns.
            Close to 1.0 means the portfolio moves closely with the market.
            Below 0.7 indicates meaningful independent return sources.
          </p>
          <Formula>Correlation = Pearson(daily_port_returns, daily_bench_returns)</Formula>
        </AccordionItem>
      </div>

      {/* Portfolio Valuation */}
      <SectionHeader title="Portfolio Valuation" />
      <div className="space-y-3">
        <AccordionItem title="NAV Calculation">
          <p>
            NAV (Net Asset Value) is the total portfolio value reported daily by the PMS
            backoffice system. It includes equity holdings at market price, cash and cash
            equivalents, and bank balance.
          </p>
        </AccordionItem>

        <AccordionItem title="TWR Index (Base 100)">
          <p>
            Time-Weighted Return normalizes both portfolio and benchmark to a starting value
            of 100, enabling fair comparison regardless of invested amounts or cash flows.
          </p>
          <Formula>TWR Index = (Current NAV / Inception NAV) x 100</Formula>
        </AccordionItem>

        <AccordionItem title="Holdings P&L (Weighted Average Cost)">
          <p>
            Current holdings are valued using the Weighted Average Cost method.
            When buying, the average cost is recalculated. When selling, average cost
            stays the same. Bonus shares dilute the average cost to zero cost for bonus units.
          </p>
          <Formula>
            {'Buy: new_avg = (old_qty x old_avg + buy_qty x buy_price) / (old_qty + buy_qty)'}
          </Formula>
          <Formula>
            {'P&L = (Current Price - Avg Cost) x Quantity'}
          </Formula>
        </AccordionItem>
      </div>

      {/* Data Sources */}
      <SectionHeader title="Data Sources & Assumptions" />
      <div className="space-y-3">
        <AccordionItem title="Data Sources">
          <ul className="list-disc list-inside space-y-1">
            <li>NAV Data: PMS backoffice daily valuation reports</li>
            <li>Benchmark: {benchmark} Total Return Index via market data feeds</li>
            <li>Risk-Free Rate: {rfr}% (India 10Y Govt Bond Yield proxy)</li>
            <li>Trading days per year: 252</li>
            <li>Cash instruments: LIQUIDBEES, LIQUIDETF treated as cash</li>
            {asOf && <li>Data as of: {formatDate(asOf)}</li>}
          </ul>
        </AccordionItem>
      </div>

      {/* Footer spacing */}
      <div className="h-10" />
    </div>
  );
}
