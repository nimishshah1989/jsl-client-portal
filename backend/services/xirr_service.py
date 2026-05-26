"""
XIRR (Extended Internal Rate of Return) computation service.

XIRR is the client's TRUE personalized return accounting for when they
actually invested money. It finds the rate r that makes the NPV of all
cash flows equal to zero.

Formula: sum(CF_i / (1 + r) ^ ((date_i - date_0) / 365)) = 0

Cash flows can come from two sources:
  1. Actual cash flow records in cpp_cash_flows (preferred)
  2. Inferred from Corpus changes in the NAV file (fallback)
"""

import logging
from datetime import date, datetime

import pandas as pd
from scipy.optimize import brentq

logger = logging.getLogger(__name__)


def extract_cash_flows_from_db(
    cashflow_records: list[tuple],  # (flow_date, flow_type, amount)
    terminal_date: datetime,
    terminal_value: float,
) -> list[tuple[datetime, float]]:
    """
    Build XIRR cash flow list from actual cash flow records in cpp_cash_flows.

    INFLOW = client investing money -> positive cash flow (money going IN to PMS)
    OUTFLOW = client withdrawing / fees -> negative cash flow (money coming OUT)
    Terminal = -(current portfolio value) on latest date
    """
    flows: list[tuple[datetime, float]] = []
    for flow_date, flow_type, amount in cashflow_records:
        if isinstance(flow_date, pd.Timestamp):
            flow_date = flow_date.to_pydatetime()
        amt = float(amount)
        if flow_type == "INFLOW":
            flows.append((flow_date, amt))
        elif flow_type == "OUTFLOW":
            flows.append((flow_date, -amt))

    # Terminal value (negative — represents the current value you could withdraw)
    if isinstance(terminal_date, pd.Timestamp):
        terminal_date = terminal_date.to_pydatetime()
    flows.append((terminal_date, -terminal_value))

    return flows


def extract_cash_flows_from_corpus(nav_df: pd.DataFrame) -> list[tuple[datetime, float]]:
    """
    Fallback: extract investment cash flows from corpus changes in NAV data.

    Used when no actual cash flow records exist in cpp_cash_flows.
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
) -> float | None:
    """
    Compute XIRR — the rate r that makes NPV of all cash flows = 0.

    Uses scipy.optimize.brentq to solve:
        sum(CF_i / (1 + r) ^ ((date_i - date_0) / 365)) = 0

    Args:
        cash_flows: List of (date, amount) tuples. Must have at least 2 entries.
                    Should contain both positive and negative amounts.
                    Order is irrelevant — flows are sorted ascending by date
                    internally before computing day offsets.
        guess: Initial guess for the rate (kept for API back-compat; unused).

    Returns:
        XIRR as a percentage (e.g., 25.5 means 25.5% annual return).

        - Returns ``0.0`` for INPUT-VALIDATION failures (fewer than two flows,
          or no sign variation in amounts). These are degenerate inputs, not
          convergence failures, and 0.0 is the historical contract.
        - Returns ``None`` when ``brentq`` cannot find a root within the
          search bracket ``[-0.99, 50.0]`` (true non-convergence). Callers
          MUST distinguish this from a genuine 0% return — previously the
          two cases were collapsed to ``0.0``, silently mis-displaying
          unconvergeable portfolios as "+0.00% XIRR".

    Notes:
        Search bracket is capped at rate=50.0 (i.e. 5000% annualised).
        Returns beyond that band are rare in practice (only achievable on
        very short, very leveraged windows) and are reported as
        non-convergence rather than risking a misleading number.
    """
    if len(cash_flows) < 2:
        logger.warning("XIRR requires at least 2 cash flows, got %d", len(cash_flows))
        return 0.0

    # Sort ascending by date so the earliest flow is the reference point.
    # Without this, an out-of-order input produces negative day offsets and
    # makes the NPV singular near rate = -1, causing brentq's bracket to
    # bracket the singularity instead of a root.
    sorted_flows = sorted(cash_flows, key=lambda cf: cf[0])
    dates = [cf[0] for cf in sorted_flows]
    amounts = [cf[1] for cf in sorted_flows]

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

    # Normalize all dates to date objects (avoid datetime vs date subtraction errors)
    def to_date(d):
        if isinstance(d, datetime):
            return d.date()
        if isinstance(d, pd.Timestamp):
            return d.date()
        return d

    dates = [to_date(d) for d in dates]
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

    # Widened bracket — a 4x return in 3 months exceeds rate 10, so the old
    # upper bound rejected legitimate (if extreme) short-window XIRRs.
    try:
        rate = brentq(npv, -0.99, 50.0, maxiter=1000)
        result = rate * 100
        logger.debug("XIRR computed: %.4f%%", result)
        return result
    except ValueError:
        date_lo = dates[0].isoformat() if dates else "n/a"
        date_hi = dates[-1].isoformat() if dates else "n/a"
        logger.warning(
            "XIRR did not converge — no root in bracket [-0.99, 50.0]; "
            "n_flows=%d, date_range=%s..%s, returning None",
            len(cash_flows), date_lo, date_hi,
        )
        return None
