/**
 * Shared formatting helpers and returns/risk section builders
 * for the calculation methodology page.
 */

export function fmt(val, decimals = 2) {
  if (val == null || isNaN(val)) return '--';
  const prefix = val > 0 ? '+' : '';
  return `${prefix}${Number(val).toFixed(decimals)}`;
}

export function fmtPct(val, decimals = 2) {
  if (val == null || isNaN(val)) return '--';
  const prefix = val > 0 ? '+' : '';
  return `${prefix}${Number(val).toFixed(decimals)}%`;
}

export function fmtRatio(val, decimals = 2) {
  if (val == null || isNaN(val)) return '--';
  return Number(val).toFixed(decimals);
}

export function buildReturnsSections(m, rf) {
  return [
    {
      title: 'Portfolio Returns',
      items: [
        {
          name: 'Absolute Return',
          value: fmtPct(m.absolute_return?.value),
          explanation:
            'The total percentage gain or loss on your portfolio from inception to today, without annualizing. This is the simplest measure of how much your money has grown.',
          formula: 'Absolute Return = (NAV_end / NAV_start) - 1',
          inputs: m.absolute_return?.inputs
            ? {
                'NAV (inception)': m.absolute_return.inputs.nav_start,
                'NAV (latest)': m.absolute_return.inputs.nav_end,
              }
            : null,
          calculation: fmtPct(m.absolute_return?.value),
          interpretation: 'Positive = profit, Negative = loss. Does not account for time.',
          benchmarkValue: fmtPct(m.absolute_return?.benchmark_value),
        },
        {
          name: 'CAGR (Compound Annual Growth Rate)',
          value: fmtPct(m.cagr?.value),
          explanation:
            'The smoothed annualized return that accounts for compounding. CAGR tells you the equivalent fixed annual rate that would have grown your money to the same amount over the same period.',
          formula: 'CAGR = ((NAV_end / NAV_start) ^ (365.25 / days)) - 1',
          inputs: m.cagr?.inputs
            ? {
                'Start Value': m.cagr.inputs.start_value,
                'End Value': m.cagr.inputs.end_value,
                'Days': m.cagr.inputs.days,
              }
            : null,
          calculation: fmtPct(m.cagr?.value),
          interpretation:
            'Uses 365.25 days/year to account for leap years. More meaningful than absolute return for periods > 1 year.',
          benchmarkValue: fmtPct(m.cagr?.benchmark_value),
        },
        {
          name: 'XIRR (Extended Internal Rate of Return)',
          value: fmtPct(m.xirr?.value),
          explanation:
            'Your personalized return that accounts for the exact timing of every cash inflow and outflow. Unlike CAGR which uses only the start and end values, XIRR considers when you actually invested additional money.',
          formula: 'NPV = Sum(CF_i / (1 + r) ^ (t_i / 365)) = 0, solve for r',
          inputs: m.xirr?.inputs
            ? {
                'Cash flows detected': `${m.xirr.inputs.num_cash_flows} corpus changes`,
                'First investment': m.xirr.inputs.first_date,
                'Latest date': m.xirr.inputs.latest_date,
              }
            : null,
          calculation: fmtPct(m.xirr?.value),
          interpretation:
            'XIRR is the rate that makes the net present value of all your cash flows equal to zero. It is the truest measure of your personal investment return.',
        },
      ],
    },
    {
      title: 'Risk Metrics',
      items: [
        {
          name: 'Volatility (Annualized)',
          value: fmtPct(m.volatility?.value),
          explanation:
            'Measures how much your portfolio value fluctuates day-to-day. Higher volatility means larger swings in both directions. Calculated as the standard deviation of daily returns, annualized by multiplying by the square root of 252 (trading days).',
          formula: 'Volatility = StdDev(daily returns) x sqrt(252)',
          inputs: m.volatility?.inputs
            ? {
                'Daily Std Dev': fmtPct(m.volatility.inputs.daily_std, 4),
                'Trading Days': '252',
              }
            : null,
          calculation: fmtPct(m.volatility?.value),
          interpretation:
            'Lower is better for risk-averse investors. 10-15% is moderate for equity portfolios.',
          benchmarkValue: fmtPct(m.volatility?.benchmark_value),
        },
        {
          name: 'Maximum Drawdown',
          value: fmtPct(m.max_drawdown?.value),
          explanation:
            'The largest peak-to-trough decline your portfolio experienced. This represents the worst-case scenario an investor would have faced if they invested at the peak and observed at the trough.',
          formula: 'Max DD = max((Peak - NAV) / Peak) over all dates',
          inputs: m.max_drawdown?.inputs
            ? {
                'Peak date': m.max_drawdown.inputs.dd_start || '--',
                'Trough date': m.max_drawdown.inputs.dd_end || '--',
                'Recovery date': m.max_drawdown.inputs.dd_recovery || 'Not recovered',
              }
            : null,
          calculation: fmtPct(m.max_drawdown?.value),
          interpretation:
            'Always negative. Closer to 0% is better. A max DD of -18% means the portfolio fell 18% from its peak before recovering.',
          benchmarkValue: fmtPct(m.max_drawdown?.benchmark_value),
        },
        {
          name: 'Sharpe Ratio',
          value: fmtRatio(m.sharpe_ratio?.value),
          explanation:
            'Measures how much excess return you receive for each unit of risk (volatility) taken. It tells you whether the returns are coming from smart investment decisions or from taking excessive risk.',
          formula: 'Sharpe = (Portfolio CAGR - Risk-Free Rate) / Volatility',
          inputs: m.sharpe_ratio?.inputs
            ? {
                'Portfolio CAGR': fmtPct(m.sharpe_ratio.inputs.portfolio_cagr),
                'Risk-Free Rate': `${rf}% (India 10Y Govt Bond)`,
                'Portfolio Volatility': fmtPct(m.sharpe_ratio.inputs.portfolio_volatility),
              }
            : null,
          calculation: fmtRatio(m.sharpe_ratio?.value),
          interpretation:
            '> 1.0 = Good risk-adjusted returns | > 2.0 = Excellent | < 0 = Returns below risk-free rate',
          benchmarkValue: fmtRatio(m.sharpe_ratio?.benchmark_value),
        },
        {
          name: 'Sortino Ratio',
          value: fmtRatio(m.sortino_ratio?.value),
          explanation:
            'Similar to Sharpe but only penalizes downside volatility. Upside volatility (gains) is not treated as risk. More appropriate for portfolios with asymmetric returns.',
          formula: 'Sortino = (Portfolio CAGR - Risk-Free Rate) / Downside Deviation',
          inputs: m.sortino_ratio?.inputs
            ? {
                'Portfolio CAGR': fmtPct(m.sortino_ratio.inputs.portfolio_cagr),
                'Risk-Free Rate': `${rf}%`,
                'Downside Deviation': fmtPct(m.sortino_ratio.inputs.downside_dev),
              }
            : null,
          calculation: fmtRatio(m.sortino_ratio?.value),
          interpretation:
            'Higher is better. Generally higher than Sharpe because it ignores upside volatility.',
          benchmarkValue: fmtRatio(m.sortino_ratio?.benchmark_value),
        },
      ],
    },
  ];
}
