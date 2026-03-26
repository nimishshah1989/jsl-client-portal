'use client';

import { formatPct, formatDate } from '@/lib/format';
import {
  AccordionItem,
  SectionHeader,
  Formula,
  Interpretation,
} from './MethodologyUI';

/**
 * Bottom sections of the methodology page:
 * Drawdown & Stress, Monthly Return Profile, Portfolio Valuation, Data Sources.
 */
export default function MethodologyAdvanced({ mv, mi, n, rfr, benchmark, asOf }) {
  return (
    <>
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
            NAV (Net Asset Value) is the total portfolio value reported daily. It includes
            equity holdings at market price, cash and cash equivalents, and bank balance.
          </p>
        </AccordionItem>

        <AccordionItem title="TWR Index (Base 100)">
          <p>
            Time-Weighted Return normalizes both portfolio and benchmark to a starting value
            of 100, enabling fair comparison regardless of invested amounts or cash flows.
            On days when new capital is added or withdrawn, the previous day&apos;s NAV is adjusted
            by the cash flow amount before computing the daily return — so the TWR only reflects
            market performance, not the effect of money moving in or out.
          </p>
          <Formula>{'Normal day: daily_return = (NAV_today / NAV_yesterday) - 1'}</Formula>
          <Formula>{'Cash flow day: daily_return = (NAV_today / (NAV_yesterday + cash_flow)) - 1'}</Formula>
          <Formula>{'TWR_t = TWR_{t-1} x (1 + daily_return_t), starting at 100'}</Formula>
        </AccordionItem>

        <AccordionItem title="Benchmark Comparison (Cash-Flow Adjusted)">
          <p>
            The benchmark line on the portfolio chart answers: &quot;What would my money be worth
            if every rupee had been invested in {benchmark} instead, at the exact same time?&quot;
          </p>
          <p>
            On each date when capital was added or withdrawn, we simulate buying or selling
            equivalent {benchmark} units at that day&apos;s index price. The benchmark value at any
            point equals the total accumulated units multiplied by the current index price.
          </p>
          <Formula>{'On inflow of ₹X on date D: nifty_units += X / Nifty_price_D'}</Formula>
          <Formula>{'On outflow of ₹Y on date D: nifty_units -= Y / Nifty_price_D'}</Formula>
          <Formula>{'Benchmark equivalent on date T = nifty_units x Nifty_price_T'}</Formula>
          <Interpretation>
            <p>This ensures the portfolio vs benchmark comparison is fair — both lines reflect
            the same money invested at the same times. Without this adjustment, new capital
            would appear as outperformance.</p>
          </Interpretation>
        </AccordionItem>

        <AccordionItem title="Holdings P&L (Weighted Average Cost)">
          <p>
            Current holdings are valued using the Weighted Average Cost method.
            When buying, the average cost is recalculated. When selling, average cost
            stays the same. Bonus shares dilute the average cost to zero cost for bonus units.
          </p>
          <Formula>{'Buy: new_avg = (old_qty x old_avg + buy_qty x buy_price) / (old_qty + buy_qty)'}</Formula>
          <Formula>{'P&L = (Current Price - Avg Cost) x Quantity'}</Formula>
        </AccordionItem>

        <AccordionItem title="Growth Comparison (Portfolio vs Nifty vs FD)">
          <p>
            Shows what your total invested capital would be worth today under three scenarios:
            your actual portfolio, a {benchmark} index fund, or a Fixed Deposit at {n(rfr) || 7}% p.a.
          </p>
          <p>
            For each cash flow (inflow or outflow), the same amount is simulated as invested in
            {benchmark} or compounded at the FD rate from that date. This accounts for the timing
            of multiple investments rather than treating all capital as a single lump sum.
          </p>
        </AccordionItem>
      </div>

      {/* Data Sources */}
      <SectionHeader title="Data Sources & Assumptions" />
      <div className="space-y-3">
        <AccordionItem title="Data Sources">
          <ul className="list-disc list-inside space-y-1">
            <li>NAV Data: Daily valuation reports</li>
            <li>Cash Flows: Actual capital inflow/outflow records with exact dates and amounts</li>
            <li>Benchmark: {benchmark} Total Return Index via market data feeds</li>
            <li>Risk-Free Rate: {rfr}% (India 10Y Govt Bond Yield proxy)</li>
            <li>Trading days per year: 252</li>
            <li>CAGR uses 365.25 days/year to account for leap years</li>
            <li>Cash instruments: LIQUIDBEES, LIQUIDETF treated as cash equivalent</li>
            {asOf && <li>Data as of: {formatDate(asOf)}</li>}
          </ul>
        </AccordionItem>
      </div>
    </>
  );
}
