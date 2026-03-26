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
