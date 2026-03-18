"""
XIRR (Extended Internal Rate of Return) computation service.

XIRR is the client's TRUE personalized return accounting for when they
actually invested money. It finds the rate r that makes the NPV of all
cash flows equal to zero.

Formula: sum(CF_i / (1 + r) ^ ((date_i - date_0) / 365)) = 0

Cash flows are derived from Corpus changes in the NAV file:
  - Corpus goes from 3.33L to 5.33L on date X -> CF = +2.00L on date X
  - Final entry: CF = -(current portfolio value) on latest date
"""

import logging
from datetime import datetime

import pandas as pd
from scipy.optimize import brentq

logger = logging.getLogger(__name__)


def extract_cash_flows(nav_df: pd.DataFrame) -> list[tuple[datetime, float]]:
    """
    Extract investment cash flows from corpus changes in NAV data.

    The Corpus column in the NAV file tracks total invested amount.
    When corpus increases, a new investment was made.
    When corpus decreases, a redemption occurred.

    Args:
        nav_df: DataFrame with columns [date, corpus, nav].
                Must be sorted ascending by date.

    Returns:
        List of (date, amount) tuples:
          - Positive amounts = money invested (cash in)
          - Negative amounts = redemptions (cash out)
          - Final entry = -(current portfolio value) on latest date
    """
    if len(nav_df) == 0:
        return []

    flows: list[tuple[datetime, float]] = []
    prev_corpus = 0.0

    for _, row in nav_df.iterrows():
        corpus = float(row["corpus"])
        flow_date = row["date"]

        # Convert pandas Timestamp to datetime if needed
        if isinstance(flow_date, pd.Timestamp):
            flow_date = flow_date.to_pydatetime()

        if corpus != prev_corpus:
            delta = corpus - prev_corpus
            flows.append((flow_date, delta))
            prev_corpus = corpus

    if len(flows) == 0:
        # No corpus changes detected — use first corpus as initial investment
        first_row = nav_df.iloc[0]
        flow_date = first_row["date"]
        if isinstance(flow_date, pd.Timestamp):
            flow_date = flow_date.to_pydatetime()
        flows.append((flow_date, float(first_row["corpus"])))

    # Add terminal value as negative (money "out" — current portfolio value)
    latest = nav_df.iloc[-1]
    terminal_date = latest["date"]
    if isinstance(terminal_date, pd.Timestamp):
        terminal_date = terminal_date.to_pydatetime()
    terminal_value = float(latest["nav"])
    flows.append((terminal_date, -terminal_value))

    return flows


def compute_xirr(
    cash_flows: list[tuple[datetime, float]],
    guess: float = 0.1,
) -> float:
    """
    Compute XIRR — the rate r that makes NPV of all cash flows = 0.

    Uses scipy.optimize.brentq to solve:
        sum(CF_i / (1 + r) ^ ((date_i - date_0) / 365)) = 0

    Args:
        cash_flows: List of (date, amount) tuples. Must have at least 2 entries.
                    Should contain both positive and negative amounts.
        guess: Initial guess for the rate (default 0.1 = 10%).

    Returns:
        XIRR as a percentage (e.g., 25.5 means 25.5% annual return).
        Returns 0.0 if no solution can be found.
    """
    if len(cash_flows) < 2:
        logger.warning("XIRR requires at least 2 cash flows, got %d", len(cash_flows))
        return 0.0

    dates = [cf[0] for cf in cash_flows]
    amounts = [cf[1] for cf in cash_flows]

    # Verify we have both positive and negative cash flows
    has_positive = any(a > 0 for a in amounts)
    has_negative = any(a < 0 for a in amounts)
    if not (has_positive and has_negative):
        logger.warning(
            "XIRR requires both positive and negative cash flows. "
            "Positive: %s, Negative: %s",
            has_positive,
            has_negative,
        )
        return 0.0

    # Days from first cash flow as year fractions
    d0 = dates[0]
    day_offsets = [(d - d0).days / 365.0 for d in dates]

    def npv(rate: float) -> float:
        """Net Present Value at the given rate."""
        total = 0.0
        for amt, t in zip(amounts, day_offsets):
            denominator = (1 + rate) ** t
            if denominator == 0:
                return float("inf")
            total += amt / denominator
        return total

    # Try brentq with a wide bracket
    try:
        rate = brentq(npv, -0.99, 10.0, maxiter=1000)
        result = rate * 100
        logger.debug("XIRR computed: %.4f%%", result)
        return result
    except ValueError:
        logger.debug("brentq failed with bracket [-0.99, 10.0], trying narrower range")

    # Fallback: try a narrower bracket
    try:
        rate = brentq(npv, -0.50, 5.0, maxiter=1000)
        return rate * 100
    except ValueError:
        logger.warning("XIRR computation failed — no root found in any bracket")
        return 0.0
