"""Tests for holdings computation service — Weighted Average Cost Method."""

from decimal import Decimal

import pandas as pd
import pytest

from backend.services.holdings_service import compute_holdings, compute_allocation


@pytest.fixture
def buy_transactions():
    """Simple buy-only transactions."""
    return pd.DataFrame([
        {"symbol": "RELIANCE", "txn_type": "BUY", "quantity": 10, "price": 2500, "asset_class": "EQUITY", "date": "2024-01-01"},
        {"symbol": "RELIANCE", "txn_type": "BUY", "quantity": 5, "price": 2600, "asset_class": "EQUITY", "date": "2024-02-01"},
        {"symbol": "TCS", "txn_type": "BUY", "quantity": 20, "price": 3500, "asset_class": "EQUITY", "date": "2024-01-15"},
    ])


@pytest.fixture
def mixed_transactions():
    """Buy, sell, and bonus transactions."""
    return pd.DataFrame([
        {"symbol": "INFY", "txn_type": "BUY", "quantity": 100, "price": 1500, "asset_class": "EQUITY", "date": "2024-01-01"},
        {"symbol": "INFY", "txn_type": "SELL", "quantity": 30, "price": 1600, "asset_class": "EQUITY", "date": "2024-03-01"},
        {"symbol": "INFY", "txn_type": "BONUS", "quantity": 14, "price": 0, "asset_class": "EQUITY", "date": "2024-06-01"},
    ])


class TestComputeHoldings:
    def test_weighted_avg_cost(self, buy_transactions):
        prices = {"RELIANCE": Decimal("2700"), "TCS": Decimal("3600")}
        result = compute_holdings(buy_transactions, prices)
        rel_row = result[result["symbol"] == "RELIANCE"].iloc[0]
        # avg = (10*2500 + 5*2600) / 15 = 38000/15 = 2533.3333
        assert rel_row["quantity"] == Decimal("15")
        assert float(rel_row["avg_cost"]) == pytest.approx(2533.3333, rel=1e-3)

    def test_sell_reduces_quantity(self, mixed_transactions):
        result = compute_holdings(mixed_transactions)
        infy = result[result["symbol"] == "INFY"].iloc[0]
        # 100 bought - 30 sold + 14 bonus = 84
        assert infy["quantity"] == Decimal("84")

    def test_bonus_dilutes_avg_cost(self, mixed_transactions):
        result = compute_holdings(mixed_transactions)
        infy = result[result["symbol"] == "INFY"].iloc[0]
        # After buy: avg=1500, qty=100. After sell: avg=1500, qty=70.
        # After bonus(14): avg = (70*1500)/84 = 1250
        assert float(infy["avg_cost"]) == pytest.approx(1250.0, rel=1e-3)

    def test_pnl_calculation(self, buy_transactions):
        prices = {"RELIANCE": Decimal("2700"), "TCS": Decimal("3600")}
        result = compute_holdings(buy_transactions, prices)
        rel = result[result["symbol"] == "RELIANCE"].iloc[0]
        # PNL = (2700 - 2533.33) * 15 ≈ 2500
        assert float(rel["unrealized_pnl"]) > 0

    def test_empty_transactions(self):
        empty = pd.DataFrame(columns=["symbol", "txn_type", "quantity", "price", "asset_class", "date"])
        result = compute_holdings(empty)
        assert result.empty

    def test_fully_sold_excluded(self):
        df = pd.DataFrame([
            {"symbol": "HDFC", "txn_type": "BUY", "quantity": 10, "price": 1000, "asset_class": "EQUITY", "date": "2024-01-01"},
            {"symbol": "HDFC", "txn_type": "SELL", "quantity": 10, "price": 1100, "asset_class": "EQUITY", "date": "2024-02-01"},
        ])
        result = compute_holdings(df)
        assert len(result) == 0

    def test_weight_pct_sums_to_100(self, buy_transactions):
        prices = {"RELIANCE": Decimal("2700"), "TCS": Decimal("3600")}
        result = compute_holdings(buy_transactions, prices)
        total_weight = float(result["weight_pct"].sum())
        assert pytest.approx(total_weight, abs=0.1) == 100.0

    def test_no_prices_zero_pnl(self, buy_transactions):
        result = compute_holdings(buy_transactions, current_prices=None)
        assert all(result["current_value"] == Decimal("0"))


class TestComputeAllocation:
    def test_empty_holdings(self):
        empty = pd.DataFrame(columns=["asset_class", "current_value", "weight_pct", "sector"])
        result = compute_allocation(empty)
        assert result == {"by_class": [], "by_sector": []}

    def test_groups_by_asset_class(self):
        df = pd.DataFrame([
            {"asset_class": "EQUITY", "current_value": Decimal("80000"), "weight_pct": Decimal("80"), "sector": "IT"},
            {"asset_class": "CASH", "current_value": Decimal("20000"), "weight_pct": Decimal("20"), "sector": "Cash"},
        ])
        result = compute_allocation(df)
        assert len(result["by_class"]) == 2
