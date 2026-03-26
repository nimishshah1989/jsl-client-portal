'use client';

import { useMethodology } from '@/hooks/usePortfolio';
import { formatPct, formatDate } from '@/lib/format';
import Spinner from '@/components/ui/Spinner';
import { Calculator } from 'lucide-react';
import {
  AccordionItem,
  SectionHeader,
  Formula,
  WorkedExample,
  Interpretation,
} from '@/components/dashboard/MethodologyUI';
import MethodologyAdvanced from '@/components/dashboard/MethodologyAdvanced';

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

  function n(v) {
    if (v == null || v === '') return null;
    const num = Number(v);
    return isNaN(num) ? null : num;
  }

  function mv(key) {
    return n(m[key]?.value);
  }

  function mi(key, input) {
    return m[key]?.inputs?.[input] ?? null;
  }

  function min(key, input) {
    return n(m[key]?.inputs?.[input]);
  }

  function mb(key) {
    return n(m[key]?.benchmark_value);
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
            <p>NAV at period start = {min('absolute_return', 'start_nav')?.toFixed(2) || '--'}</p>
            <p>NAV at period end = {min('absolute_return', 'end_nav')?.toFixed(2) || '--'}</p>
            <p className="mt-2 font-semibold text-slate-800">
              = ({min('absolute_return', 'end_nav')?.toFixed(2) || '--'} / {min('absolute_return', 'start_nav')?.toFixed(2) || '--'}) - 1
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
            <p>Start Value = {min('cagr', 'start_value')?.toFixed(2) || '--'}</p>
            <p>End Value = {min('cagr', 'end_value')?.toFixed(2) || '--'}</p>
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
            investment you made. Unlike CAGR (which only uses start and end values), XIRR
            reflects when you actually put money in and took money out.
          </p>
          <Formula>
            {'XIRR: Find rate r where Sum(CF_i / (1+r)^((date_i - date_0)/365)) = 0'}
          </Formula>
          <WorkedExample>
            <p>Cash flow source: {mi('xirr', 'cash_flow_source') || 'Actual PMS records'}</p>
            <p>First investment date: {mi('xirr', 'first_date') || '--'}</p>
            <p>Total invested: ₹{mi('xirr', 'total_invested') || '--'}</p>
            <p className="mt-2 font-semibold text-slate-800">
              = <span className="text-teal-600">{formatPct(mv('xirr'))}</span>
            </p>
          </WorkedExample>
          <Interpretation>
            <p>Solved numerically using Brent&apos;s method. Cash flows are sourced from actual
            PMS inflow/outflow records (capital additions and withdrawals with exact dates
            and amounts). The terminal cash flow is the current portfolio value treated as
            a final withdrawal.</p>
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
            <p>Daily return std dev = {min('volatility', 'daily_std')?.toFixed(4) || '--'}</p>
            <p className="mt-2 font-semibold text-slate-800">
              = {min('volatility', 'daily_std')?.toFixed(4) || '--'} x {Math.sqrt(252).toFixed(2)}
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
            <p>Portfolio CAGR = {formatPct(min('sharpe_ratio', 'portfolio_cagr'))}</p>
            <p>Risk-Free Rate = {rfr}% (India 10Y Govt Bond)</p>
            <p>Portfolio Volatility = {formatPct(min('sharpe_ratio', 'portfolio_volatility'))}</p>
            <p className="mt-2 font-semibold text-slate-800">
              = ({min('sharpe_ratio', 'portfolio_cagr')?.toFixed(2) || '--'} - {rfr}) / {min('sharpe_ratio', 'portfolio_volatility')?.toFixed(2) || '--'}
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
            <p>Portfolio CAGR = {formatPct(min('sortino_ratio', 'portfolio_cagr'))}</p>
            <p>Risk-Free Rate = {rfr}%</p>
            <p>Downside Deviation = {formatPct(min('sortino_ratio', 'downside_dev'))}</p>
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
            Excess return beyond what the portfolio&apos;s market risk (beta) would predict.
            Positive alpha means the manager/strategy adds value above pure market exposure.
          </p>
          <Formula>{'Alpha = R_p - [R_f + Beta x (R_b - R_f)]'}</Formula>
          <WorkedExample>
            <p>Portfolio CAGR (R_p) = {formatPct(min('alpha', 'port_cagr'))}</p>
            <p>Benchmark CAGR (R_b) = {formatPct(min('alpha', 'bench_cagr'))}</p>
            <p>Beta = {min('alpha', 'beta')?.toFixed(2) || '--'}</p>
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
            What percentage of the benchmark&apos;s gains the portfolio captures on up days.
            Above 100% means the portfolio gains more than the market when it rises.
          </p>
          <Formula>Up Capture = Mean(port returns on UP days) / Mean(bench returns on UP days) x 100</Formula>
        </AccordionItem>

        <AccordionItem title="Down Capture Ratio" value={mv('down_capture')}>
          <p>
            What percentage of the benchmark&apos;s losses the portfolio absorbs on down days.
            Below 100% means the portfolio loses less than the market when it falls.
          </p>
          <Formula>Down Capture = Mean(port returns on DOWN days) / Mean(bench returns on DOWN days) x 100</Formula>
          <Interpretation>
            <p>Ideal: Low down capture + reasonable up capture = asymmetric returns.</p>
          </Interpretation>
        </AccordionItem>
      </div>

      {/* Advanced sections (Drawdown, Monthly, Valuation, Data Sources) */}
      <MethodologyAdvanced
        mv={mv} mi={mi} n={n}
        rfr={rfr} benchmark={benchmark} asOf={asOf}
      />

      {/* Footer spacing */}
      <div className="h-10" />
    </div>
  );
}
