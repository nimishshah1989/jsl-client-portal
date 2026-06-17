"""The holdings table's cash + reconciling rows must close the weights to 100%.

Equity rows are priced at live CMP but weighted on the official NAV; when the
NAV's equity mark exceeds our itemised positions, a reconciling "Other" line
keeps equity + cash + residual = 100%.
"""

import os

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("JWT_SECRET", "a" * 64)

from decimal import Decimal

from backend.routers.portfolio import _build_cash_lines


def _weight_sum(equity_total: Decimal, total_value: Decimal, items) -> float:
    equity_pct = float(equity_total / total_value * 100)
    return equity_pct + sum(float(i.weight_pct) for i in items)


def test_residual_line_closes_weights_to_100():
    # NAV 100; itemised equity 60, undeployed cash 20 → 20 unexplained (a holding
    # awaiting a price refresh). The reconciling line must surface it.
    items = _build_cash_lines(Decimal("60"), Decimal("20"), Decimal("0"), Decimal("100"))
    labels = {i.label for i in items}
    assert "Undeployed Cash" in labels
    assert "Other (broker valuation)" in labels
    assert abs(_weight_sum(Decimal("60"), Decimal("100"), items) - 100.0) < 0.05


def test_no_residual_line_when_already_reconciled():
    # NAV 100 = equity 70 + cash 30 → no gap, no reconciling line.
    items = _build_cash_lines(Decimal("70"), Decimal("30"), Decimal("0"), Decimal("100"))
    assert all("Other" not in i.label for i in items)
    assert abs(_weight_sum(Decimal("70"), Decimal("100"), items) - 100.0) < 0.05


def test_tiny_residual_ignored_as_rounding_noise():
    # 0.2% gap is below the 0.5% threshold → not surfaced.
    items = _build_cash_lines(Decimal("79.8"), Decimal("20"), Decimal("0"), Decimal("100"))
    assert all("Other" not in i.label for i in items)


def test_negative_residual_not_shown():
    # Itemised equity (110) exceeds NAV (100) — stale-high price; no line.
    items = _build_cash_lines(Decimal("110"), Decimal("0"), Decimal("0"), Decimal("100"))
    assert all("Other" not in i.label for i in items)
