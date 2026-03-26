/**
 * Build methodology accordion sections from API data.
 * Returns/risk sections extracted to methodology-helpers.js.
 */

import { buildReturnsSections, fmtPct, fmtRatio } from './methodology-helpers';

export function buildSections(data) {
  if (!data || !data.metrics) return [];

  const m = data.metrics;
  const rf = data.risk_free_rate ?? 6.5;
  const bench = data.benchmark_name ?? 'NIFTY 50';

  const returnsSections = buildReturnsSections(m, rf);

  const remainingSections = [
    {
      title: 'Benchmark Comparison',
      items: [
        {
          name: 'Alpha (Jensen\'s Alpha)',
          value: fmtPct(m.alpha?.value),
          explanation:
            `Excess return beyond what the portfolio's market risk (beta) would predict. Positive alpha means the fund manager's strategy adds value above simply taking market exposure.`,
          formula: 'Alpha = R_portfolio - [R_f + Beta x (R_benchmark - R_f)]',
          inputs: m.alpha?.inputs
            ? {
                'Portfolio CAGR': fmtPct(m.alpha.inputs.port_cagr),
                'Benchmark CAGR': fmtPct(m.alpha.inputs.bench_cagr),
                'Beta': fmtRatio(m.alpha.inputs.beta_val),
                'Risk-Free Rate': `${rf}%`,
              }
            : null,
          calculation: fmtPct(m.alpha?.value),
          interpretation: 'Positive = outperformance vs. expected risk-adjusted return. Higher is better.',
        },
        {
          name: 'Beta',
          value: fmtRatio(m.beta?.value),
          explanation:
            `Measures portfolio sensitivity to market movements. A beta of 1.0 means the portfolio moves exactly with the ${bench}. Less than 1.0 means less volatile than the market (defensive).`,
          formula: 'Beta = Covariance(R_portfolio, R_benchmark) / Variance(R_benchmark)',
          inputs: null,
          calculation: fmtRatio(m.beta?.value),
          interpretation:
            'Beta = 1.0: matches market | < 1.0: defensive | > 1.0: aggressive. Multi-asset portfolios typically show Beta < 1 due to cash and diversification.',
        },
        {
          name: 'Information Ratio',
          value: fmtRatio(m.information_ratio?.value),
          explanation:
            'Measures risk-adjusted excess return over the benchmark. It answers: "How much excess return am I getting per unit of active risk (deviation from benchmark)?"',
          formula: 'IR = (Portfolio CAGR - Benchmark CAGR) / Tracking Error',
          inputs: m.information_ratio?.inputs
            ? {
                'Portfolio CAGR': fmtPct(m.information_ratio.inputs.port_cagr),
                'Benchmark CAGR': fmtPct(m.information_ratio.inputs.bench_cagr),
                'Tracking Error': fmtPct(m.information_ratio.inputs.tracking_error),
              }
            : null,
          calculation: fmtRatio(m.information_ratio?.value),
          interpretation: '> 0.5 = good active management | > 1.0 = excellent',
        },
        {
          name: 'Tracking Error',
          value: fmtPct(m.tracking_error?.value),
          explanation:
            'Annualized standard deviation of the difference between portfolio and benchmark returns. High tracking error means the portfolio deviates significantly from the benchmark.',
          formula: 'TE = StdDev(R_portfolio - R_benchmark) x sqrt(252)',
          inputs: null,
          calculation: fmtPct(m.tracking_error?.value),
          interpretation: 'Low TE = index-like | High TE = highly active management',
        },
        {
          name: 'Up Capture Ratio',
          value: m.up_capture?.value != null ? `${fmtRatio(m.up_capture.value, 1)}%` : '--',
          explanation:
            `Measures what percentage of the ${bench}'s gains the portfolio captures on days when the market rises. Above 100% means the portfolio gains more than the market on up days.`,
          formula: 'Up Capture = mean(portfolio return on UP days) / mean(benchmark return on UP days) x 100',
          inputs: null,
          calculation: m.up_capture?.value != null ? `${fmtRatio(m.up_capture.value, 1)}%` : '--',
          interpretation: '> 100% = captures more than market gains | < 100% = captures less',
          benchmarkValue: '100% (by definition)',
        },
        {
          name: 'Down Capture Ratio',
          value: m.down_capture?.value != null ? `${fmtRatio(m.down_capture.value, 1)}%` : '--',
          explanation:
            `Measures what percentage of the ${bench}'s losses the portfolio absorbs on days when the market falls. Below 100% is desirable — it means you lose less than the market on bad days.`,
          formula: 'Down Capture = mean(portfolio return on DOWN days) / mean(benchmark return on DOWN days) x 100',
          inputs: null,
          calculation: m.down_capture?.value != null ? `${fmtRatio(m.down_capture.value, 1)}%` : '--',
          interpretation:
            '< 100% = loses less than market (goal) | > 100% = loses more than market. Ideal: low down capture + reasonable up capture = asymmetric returns.',
          benchmarkValue: '100% (by definition)',
        },
      ],
    },
    {
      title: 'Drawdown & Stress',
      items: [
        {
          name: 'Ulcer Index',
          value: fmtRatio(m.ulcer_index?.value),
          explanation:
            'Unlike Maximum Drawdown which shows only the worst decline, Ulcer Index measures the depth AND duration of ALL drawdowns via their root-mean-square. It captures the sustained pain of being underwater.',
          formula: 'Ulcer Index = sqrt(mean(Drawdown_i^2))',
          inputs: null,
          calculation: fmtRatio(m.ulcer_index?.value),
          interpretation:
            '0-2: Very low stress | 2-5: Low stress | 5-10: Moderate | 10-20: High | 20+: Severe',
          benchmarkValue: fmtRatio(m.ulcer_index?.benchmark_value),
        },
        {
          name: 'Maximum Consecutive Loss Months',
          value: m.max_consecutive_loss?.value != null ? `${m.max_consecutive_loss.value} months` : '--',
          explanation:
            'The longest streak of consecutive months with negative returns. Longer streaks test investor patience and conviction.',
          formula: 'Count the longest unbroken run of months where monthly return <= 0',
          inputs: null,
          calculation: m.max_consecutive_loss?.value != null ? `${m.max_consecutive_loss.value} months` : '--',
          interpretation: '1-2 months: normal | 3-4: notable | 5+: extended downturn',
        },
        {
          name: 'Average Cash Held',
          value: m.avg_cash_held?.value != null ? fmtPct(m.avg_cash_held.value, 1) : '--',
          explanation:
            'Average cash and liquid fund allocation as a percentage of NAV across all days. Higher values indicate a more defensive average positioning.',
          formula: 'Average of daily Liquidity % from NAV file',
          inputs: null,
          calculation: m.avg_cash_held?.value != null ? fmtPct(m.avg_cash_held.value, 1) : '--',
          interpretation: 'Higher cash = more defensive posture. Tactical cash management is a key part of the strategy.',
        },
        {
          name: 'Maximum Cash Held',
          value: m.max_cash_held?.value != null ? fmtPct(m.max_cash_held.value, 1) : '--',
          explanation:
            'The highest percentage of portfolio held in cash on any single day. Shows the willingness to go heavily defensive during periods of perceived market risk.',
          formula: 'Maximum of daily Liquidity % from NAV file',
          inputs: null,
          calculation: m.max_cash_held?.value != null ? fmtPct(m.max_cash_held.value, 1) : '--',
          interpretation: 'Peak defensive positioning — shows how aggressively the strategy can reduce market exposure.',
        },
      ],
    },
    {
      title: 'Monthly Return Profile',
      items: [
        {
          name: 'Monthly Hit Rate',
          value: m.hit_rate?.value != null ? fmtPct(m.hit_rate.value, 1) : '--',
          explanation:
            'The percentage of months with positive returns. A hit rate above 50% means the portfolio is profitable more months than not.',
          formula: 'Hit Rate = (positive months / total months) x 100',
          inputs: m.hit_rate?.inputs
            ? {
                'Positive months': m.hit_rate.inputs.win_count,
                'Total months': m.hit_rate.inputs.total_months,
              }
            : null,
          calculation: m.hit_rate?.value != null ? fmtPct(m.hit_rate.value, 1) : '--',
          interpretation: '> 55%: good | > 65%: excellent | < 50%: more losing months than winning',
        },
        {
          name: 'Best / Worst Month',
          value: m.best_month?.value != null
            ? `${fmtPct(m.best_month.value)} / ${fmtPct(m.worst_month?.value)}`
            : '--',
          explanation:
            'The highest and lowest single-month returns. Together they define the range of monthly outcomes experienced.',
          formula: 'Max and Min of all monthly returns',
          inputs: null,
          calculation: m.best_month?.value != null
            ? `Best: ${fmtPct(m.best_month.value)}, Worst: ${fmtPct(m.worst_month?.value)}`
            : '--',
          interpretation: 'A narrow range indicates consistent returns. A wide range suggests higher volatility.',
        },
        {
          name: 'Market Correlation',
          value: fmtRatio(m.market_correlation?.value),
          explanation:
            `The Pearson correlation coefficient between daily portfolio returns and ${bench} returns. Ranges from -1 to +1.`,
          formula: 'rho = Pearson Correlation(daily portfolio returns, daily benchmark returns)',
          inputs: null,
          calculation: fmtRatio(m.market_correlation?.value),
          interpretation:
            'Close to 1.0 = moves closely with market | Below 0.7 = meaningful independent return sources | Close to 0 = almost no relationship to market',
        },
      ],
    },
    {
      title: 'Portfolio Valuation',
      items: [
        {
          name: 'NAV Calculation',
          value: null,
          explanation:
            'NAV (Net Asset Value) is the total market value of all holdings plus cash, minus any liabilities. The PMS backoffice computes this daily based on closing market prices.',
          formula: 'NAV = Market Value of Equity Holdings + Cash & Cash Equivalents + Bank Balance',
          inputs: null,
          calculation: null,
          interpretation: 'This is an absolute value in rupees, not a per-unit value like mutual funds.',
        },
        {
          name: 'TWR Index (Base 100)',
          value: null,
          explanation:
            'Time-Weighted Return normalizes the NAV to a base of 100 from inception, eliminating the effect of cash inflows and outflows. This makes it possible to compare portfolios of different sizes fairly.',
          formula: 'TWR Index = (NAV_today / NAV_inception) x 100',
          inputs: null,
          calculation: null,
          interpretation: 'Both portfolio and benchmark start at 100 and diverge based on performance.',
        },
        {
          name: 'Holdings P&L (Weighted Average Cost)',
          value: null,
          explanation:
            'Holdings profit and loss is calculated using the Weighted Average Cost method. When buying, the average cost is recalculated. When selling, the average cost remains unchanged. Bonus shares dilute the average cost to zero cost for the bonus quantity.',
          formula: 'Unrealized P&L = (Current Price - Avg Cost) x Quantity',
          inputs: null,
          calculation: null,
          interpretation:
            'P&L % = ((Current Price / Avg Cost) - 1) x 100. Green indicates profit, red indicates loss.',
        },
        {
          name: 'Growth Comparison',
          value: null,
          explanation:
            `The "What your money became" chart compares your actual portfolio value against what the same amount invested in the ${bench} or a Fixed Deposit (7% p.a.) would have grown to.`,
          formula: 'FD Value = Invested x (1 + 7%)^years | Nifty Value = Invested x (Nifty_end / Nifty_start)',
          inputs: null,
          calculation: null,
          interpretation: 'Helps you understand the opportunity cost vs. other investment options.',
        },
      ],
    },
    {
      title: 'Data Sources & Assumptions',
      items: [
        {
          name: 'NAV Data Source',
          value: null,
          explanation:
            'Daily NAV data is sourced from the PMS backoffice valuation system. It includes market value of all equity holdings, cash positions, and bank balances, computed at end of each trading day.',
          formula: null,
          inputs: null,
          calculation: null,
          interpretation: null,
        },
        {
          name: `Benchmark: ${bench}`,
          value: null,
          explanation:
            `The ${bench} Total Return Index is used as the benchmark for all comparisons. This index includes dividends reinvested, making it a fair comparison against the portfolio which also benefits from dividends.`,
          formula: null,
          inputs: null,
          calculation: null,
          interpretation: 'Benchmark data is fetched daily and aligned to portfolio trading dates.',
        },
        {
          name: `Risk-Free Rate: ${rf}%`,
          value: null,
          explanation:
            'The risk-free rate is set at 6.50%, which approximates the India 10-Year Government Bond yield. This is used in Sharpe Ratio, Sortino Ratio, Alpha, and other risk-adjusted metrics.',
          formula: null,
          inputs: null,
          calculation: null,
          interpretation: 'Updated periodically. All metrics will recalculate when the rate changes.',
        },
        {
          name: 'Trading Days: 252 per year',
          value: null,
          explanation:
            'The Indian stock market (NSE) has approximately 248-252 trading days per year. We use 252 as the standard for annualizing daily volatility and other metrics.',
          formula: null,
          inputs: null,
          calculation: null,
          interpretation: null,
        },
        {
          name: 'Cash Instruments',
          value: null,
          explanation:
            'LIQUIDBEES, LIQUIDETF, and similar liquid fund holdings are treated as cash equivalents in asset allocation. The Liquidity % from the NAV file directly provides this metric.',
          formula: null,
          inputs: null,
          calculation: null,
          interpretation: null,
        },
        {
          name: 'As-of Date',
          value: data.as_of_date || '--',
          explanation:
            'All metrics are computed as of the latest available NAV date. Data freshness depends on when the admin last uploaded NAV files.',
          formula: null,
          inputs: null,
          calculation: null,
          interpretation: null,
        },
      ],
    },
  ];

  return [...returnsSections, ...remainingSections];
}
