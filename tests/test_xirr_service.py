"""Tests for XIRR computation service."""

from datetime import datetime, date

import pandas as pd
import pytest

from backend.services.xirr_service import (
    compute_xirr,
    extract_cash_flows_from_corpus,
    extract_cash_flows_from_db,
)


# ── compute_xirr ──


class TestComputeXIRR:
    def test_simple_doubling_one_year(self):
        """Invest 100, worth 200 after 1 year → ~100% XIRR."""
        flows = [
            (datetime(2024, 1, 1), 100.0),
            (datetime(2025, 1, 1), -200.0),
        ]
        result = compute_xirr(flows)
        assert pytest.approx(result, rel=0.01) == 100.0

    def test_simple_50pct_return(self):
        """Invest 100, worth 150 after 1 year → ~50% XIRR."""
        flows = [
            (datetime(2024, 1, 1), 100.0),
            (datetime(2025, 1, 1), -150.0),
        ]
        result = compute_xirr(flows)
        assert pytest.approx(result, rel=0.01) == 50.0

    def test_multiple_investments(self):
        """Two investments at different times, positive return."""
        flows = [
            (datetime(2024, 1, 1), 100.0),   # Initial investment
            (datetime(2024, 7, 1), 50.0),     # Additional investment
            (datetime(2025, 1, 1), -180.0),   # Terminal value
        ]
        result = compute_xirr(flows)
        assert result > 0  # Should be positive

    def test_loss_scenario(self):
        """Invest 100, worth 80 after 1 year → negative XIRR."""
        flows = [
            (datetime(2024, 1, 1), 100.0),
            (datetime(2025, 1, 1), -80.0),
        ]
        result = compute_xirr(flows)
        assert result < 0

    def test_too_few_flows(self):
        """Less than 2 cash flows returns 0."""
        assert compute_xirr([(datetime(2024, 1, 1), 100.0)]) == 0.0
        assert compute_xirr([]) == 0.0

    def test_all_positive_flows(self):
        """All positive cash flows (no terminal) → returns 0."""
        flows = [
            (datetime(2024, 1, 1), 100.0),
            (datetime(2024, 7, 1), 50.0),
        ]
        assert compute_xirr(flows) == 0.0

    def test_all_negative_flows(self):
        """All negative cash flows → returns 0."""
        flows = [
            (datetime(2024, 1, 1), -100.0),
            (datetime(2024, 7, 1), -50.0),
        ]
        assert compute_xirr(flows) == 0.0

    def test_handles_date_objects(self):
        """Works with date objects (not just datetime)."""
        flows = [
            (date(2024, 1, 1), 100.0),
            (date(2025, 1, 1), -150.0),
        ]
        result = compute_xirr(flows)
        assert pytest.approx(result, rel=0.01) == 50.0

    def test_handles_pandas_timestamps(self):
        """Works with pandas Timestamp objects."""
        flows = [
            (pd.Timestamp("2024-01-01"), 100.0),
            (pd.Timestamp("2025-01-01"), -150.0),
        ]
        result = compute_xirr(flows)
        assert pytest.approx(result, rel=0.01) == 50.0

    def test_withdrawal_scenario(self):
        """Investment with a partial withdrawal in between."""
        flows = [
            (datetime(2024, 1, 1), 100.0),   # Invest 100
            (datetime(2024, 7, 1), -30.0),    # Withdraw 30
            (datetime(2025, 1, 1), -90.0),    # Terminal value 90
        ]
        result = compute_xirr(flows)
        assert result > 0  # Net gain: put in 100, took out 120


# ── extract_cash_flows_from_db ──


class TestExtractCashFlowsFromDB:
    def test_basic_inflows(self):
        records = [
            (datetime(2024, 1, 1), "INFLOW", 100000),
            (datetime(2024, 6, 1), "INFLOW", 50000),
        ]
        flows = extract_cash_flows_from_db(
            records,
            terminal_date=datetime(2025, 1, 1),
            terminal_value=200000,
        )
        assert len(flows) == 3
        assert flows[0] == (datetime(2024, 1, 1), 100000.0)
        assert flows[1] == (datetime(2024, 6, 1), 50000.0)
        assert flows[2] == (datetime(2025, 1, 1), -200000.0)

    def test_outflow_is_negative(self):
        records = [
            (datetime(2024, 1, 1), "INFLOW", 100000),
            (datetime(2024, 6, 1), "OUTFLOW", 20000),
        ]
        flows = extract_cash_flows_from_db(
            records,
            terminal_date=datetime(2025, 1, 1),
            terminal_value=90000,
        )
        assert flows[1] == (datetime(2024, 6, 1), -20000.0)

    def test_pandas_timestamp_conversion(self):
        records = [
            (pd.Timestamp("2024-01-01"), "INFLOW", 100000),
        ]
        flows = extract_cash_flows_from_db(
            records,
            terminal_date=pd.Timestamp("2025-01-01"),
            terminal_value=150000,
        )
        assert len(flows) == 2
        assert isinstance(flows[0][0], datetime)


# ── extract_cash_flows_from_corpus ──


class TestExtractCashFlowsFromCorpus:
    def test_single_corpus_change(self):
        nav_df = pd.DataFrame({
            "date": [datetime(2024, 1, 1), datetime(2024, 6, 1), datetime(2025, 1, 1)],
            "corpus": [100000, 150000, 150000],
            "nav": [100000, 155000, 180000],
        })
        flows = extract_cash_flows_from_corpus(nav_df)
        assert len(flows) == 3  # Initial + corpus change + terminal
        assert flows[0][1] == 100000.0  # Initial corpus
        assert flows[1][1] == 50000.0   # Corpus increased by 50K
        assert flows[2][1] == -180000.0  # Terminal (negative)

    def test_no_corpus_changes(self):
        """When corpus never changes, still gets initial + terminal."""
        nav_df = pd.DataFrame({
            "date": [datetime(2024, 1, 1), datetime(2025, 1, 1)],
            "corpus": [100000, 100000],
            "nav": [100000, 120000],
        })
        flows = extract_cash_flows_from_corpus(nav_df)
        assert len(flows) == 2
        assert flows[0][1] == 100000.0   # Initial
        assert flows[1][1] == -120000.0  # Terminal

    def test_empty_dataframe(self):
        nav_df = pd.DataFrame(columns=["date", "corpus", "nav"])
        flows = extract_cash_flows_from_corpus(nav_df)
        assert flows == []

    def test_corpus_decrease_is_negative(self):
        """Corpus decrease = withdrawal = negative cash flow."""
        nav_df = pd.DataFrame({
            "date": [datetime(2024, 1, 1), datetime(2024, 6, 1), datetime(2025, 1, 1)],
            "corpus": [100000, 80000, 80000],
            "nav": [100000, 85000, 90000],
        })
        flows = extract_cash_flows_from_corpus(nav_df)
        # First flow = 100K (initial), second = -20K (decrease), terminal = -90K
        assert flows[0][1] == 100000.0
        assert flows[1][1] == -20000.0
        assert flows[2][1] == -90000.0


# ── Integration: extract + compute ──


class TestXIRRIntegration:
    def test_db_flows_to_xirr(self):
        """End-to-end: DB records → cash flows → XIRR."""
        records = [
            (datetime(2024, 1, 1), "INFLOW", 100000),
        ]
        flows = extract_cash_flows_from_db(
            records,
            terminal_date=datetime(2025, 1, 1),
            terminal_value=120000,
        )
        xirr = compute_xirr(flows)
        assert pytest.approx(xirr, rel=0.01) == 20.0

    def test_corpus_flows_to_xirr(self):
        """End-to-end: NAV data → corpus flows → XIRR."""
        nav_df = pd.DataFrame({
            "date": [datetime(2024, 1, 1), datetime(2025, 1, 1)],
            "corpus": [100000, 100000],
            "nav": [100000, 130000],
        })
        flows = extract_cash_flows_from_corpus(nav_df)
        xirr = compute_xirr(flows)
        assert pytest.approx(xirr, rel=0.01) == 30.0


# ── Regression tests for robustness fixes (Sprint 2) ──


class TestXIRRRobustness:
    """Three robustness fixes:
      1. out-of-order cash flows are sorted internally
      2. brentq bracket widened to handle >10x annualised rates (e.g. 4x in 3mo)
      3. non-convergence returns None (not 0.0) so callers can distinguish
         "couldn't compute" from a real 0% return.
    """

    def test_out_of_order_cash_flows_match_in_order(self):
        """Permuting input order must not change the XIRR result.

        Previously, an unsorted input made d0 = first-element-as-given,
        which produced negative day offsets and bracket failure.
        """
        in_order = [
            (datetime(2024, 1, 1), 100.0),
            (datetime(2024, 7, 1), 50.0),
            (datetime(2025, 1, 1), -180.0),
        ]
        # Same flows, reversed
        reversed_order = list(reversed(in_order))
        # Same flows, arbitrary permutation
        shuffled = [in_order[2], in_order[0], in_order[1]]

        r_in = compute_xirr(in_order)
        r_rev = compute_xirr(reversed_order)
        r_shuf = compute_xirr(shuffled)

        assert r_in is not None
        assert r_rev is not None
        assert r_shuf is not None
        assert pytest.approx(r_in, rel=1e-6) == r_rev
        assert pytest.approx(r_in, rel=1e-6) == r_shuf

    def test_high_short_window_return_no_longer_zero(self):
        """A 2x return in ~3 months annualises to (1+r) = 2^(365/91) ≈ 16,
        so rate ≈ 15 — beyond the old upper bracket of 10. Previously this
        fell through to the narrow fallback bracket [-0.5, 5.0] and was
        reported as 0.0 (indistinguishable from a flat portfolio). With the
        widened [-0.99, 50.0] bracket it must now resolve to a large
        positive XIRR.
        """
        flows = [
            (datetime(2024, 1, 1), 100.0),    # Invest ₹100
            (datetime(2024, 4, 1), -200.0),   # Worth ₹200 ~91 days later
        ]
        result = compute_xirr(flows)
        assert result is not None, "Should converge, not return None"
        # Annualised should be well above 1000% — definitely not 0.
        assert result > 1000.0, (
            f"Expected a >1000% XIRR for a 2x quarterly return; got {result}. "
            f"Bracket likely still too narrow."
        )

    def test_xirr_handles_mixed_date_and_datetime(self):
        """Production hot-fix 2026-05-26: cash_flows arriving as a MIX of
        ``datetime.date`` and ``datetime.datetime`` (and pandas Timestamp)
        used to raise ``TypeError: can't compare datetime.datetime to
        datetime.date`` inside the sort key, which broke recompute for
        356/363 PMS clients.

        The list must be normalized to ``datetime.date`` BEFORE the sort,
        not after, so this test exercises the exact mixed-type pattern that
        hit production.
        """
        import datetime as _dt
        flows = [
            (_dt.date(2020, 1, 1), -100_000),
            (_dt.datetime(2024, 6, 15, 9, 30), -50_000),
            (_dt.date(2026, 5, 25), 175_000),
        ]
        # Must not raise. Result may be a positive rate or None (no root),
        # but it MUST be a "couldn't-explode" pass.
        result = compute_xirr(flows)
        # Spec from PR description: must not raise; should return a
        # reasonable rate (or None if non-convergent).
        assert result is None or (-1 < result < 5), (
            f"Mixed date/datetime input must produce a sane rate; got {result}"
        )

    def test_unconvergeable_input_returns_none(self):
        """When brentq genuinely cannot find a root, compute_xirr must
        return None — NOT 0.0 — so callers can render "N/A" instead of
        silently showing a misleading "+0.00% XIRR".

        Construct cash flows whose NPV(rate) has the same sign across the
        entire search bracket: a huge near-instant gain that compounds
        faster than rate=50 across the whole [-0.99, 50.0] window.
        """
        flows = [
            (datetime(2024, 1, 1), 1.0),                 # Invest ₹1
            (datetime(2024, 1, 2), -1_000_000_000.0),    # Worth ₹1bn the next day
        ]
        result = compute_xirr(flows)
        # The hallmark of the fix: non-convergence must NOT collapse to 0.
        assert result is None, (
            f"Expected None for unconvergeable input; got {result!r}. "
            f"Previously this was indistinguishable from a genuine 0% XIRR."
        )
