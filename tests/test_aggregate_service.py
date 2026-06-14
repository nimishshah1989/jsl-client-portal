"""Tests for aggregate service — composite index and range filter functions.

Tests the pure functions _build_composite_from_returns and _apply_range_filter
by reimplementing the same logic to avoid the deep SQLAlchemy model import chain
which requires database configuration.

Also includes regression tests for the TWR corpus-adjustment fix in
``_fetch_daily_composite_returns``. Those tests execute the production SQL
against an in-memory SQLite database (SQLite 3.25+ supports window functions
including LAG, which is all the SQL needs) populated with synthetic NAV rows
where corpus changes mid-stream. They guard against regressions of the bug
that produced a +625% aggregate Since-Inception return.
"""

import sqlite3
from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest


# ── Reimplemented pure functions (matching aggregate_service.py logic) ──

RANGE_DAYS = {
    "1M": 30, "3M": 91, "6M": 182, "1Y": 365,
    "2Y": 730, "3Y": 1095, "5Y": 1826, "ALL": None,
}


def _build_composite_from_returns(daily_rets: pd.DataFrame):
    """Build composite index from pre-computed AUM-weighted daily returns."""
    if daily_rets.empty:
        return pd.Series(dtype=float), pd.Series(dtype=float)

    port_ret = daily_rets["weighted_port_ret"].values
    bench_ret = daily_rets["weighted_bench_ret"].values

    port_cum = 100.0 * np.cumprod(1.0 + port_ret)
    bench_cum = 100.0 * np.cumprod(1.0 + bench_ret)

    dates = daily_rets["nav_date"].values
    first_date = dates[0] - pd.Timedelta(days=1)
    all_dates = np.concatenate([[first_date], dates])

    port_index = np.concatenate([[100.0], port_cum])
    bench_index = np.concatenate([[100.0], bench_cum])

    idx = pd.DatetimeIndex(all_dates)
    return pd.Series(port_index, index=idx), pd.Series(bench_index, index=idx)


def _apply_range_filter(df: pd.DataFrame, range_filter: str) -> pd.DataFrame:
    """Slice DataFrame to trailing N days based on range_filter."""
    days = RANGE_DAYS.get(range_filter.upper())
    if days is None or df.empty:
        return df
    cutoff = df["nav_date"].iloc[-1] - pd.Timedelta(days=days)
    return df[df["nav_date"] >= cutoff].reset_index(drop=True)


# ── Fixtures ──


@pytest.fixture
def sample_daily_returns():
    """DataFrame with nav_date, weighted_port_ret, weighted_bench_ret."""
    dates = pd.date_range("2025-01-02", periods=5, freq="D")
    return pd.DataFrame({
        "nav_date": dates,
        "weighted_port_ret": [0.01, -0.005, 0.02, 0.003, -0.01],
        "weighted_bench_ret": [0.008, -0.003, 0.015, 0.002, -0.008],
    })


@pytest.fixture
def sample_agg_df():
    """Aggregate NAV DataFrame with nav_date column for range filtering."""
    dates = pd.date_range("2024-01-01", periods=400, freq="D")
    return pd.DataFrame({
        "nav_date": dates,
        "total_aum": np.random.uniform(1e8, 2e8, size=400),
        "total_invested": np.linspace(1e8, 1.5e8, 400),
        "weighted_cash_pct": np.random.uniform(5, 15, size=400),
    })


# ── _build_composite_from_returns tests ──


class TestBuildCompositeFromReturns:
    def test_produces_base_100_start(self, sample_daily_returns):
        port, bench = _build_composite_from_returns(sample_daily_returns)
        assert port.iloc[0] == 100.0
        assert bench.iloc[0] == 100.0

    def test_length_is_returns_plus_one(self, sample_daily_returns):
        """Output should have N+1 entries (base + N days of returns)."""
        port, bench = _build_composite_from_returns(sample_daily_returns)
        assert len(port) == len(sample_daily_returns) + 1
        assert len(bench) == len(sample_daily_returns) + 1

    def test_cumulative_returns_correct(self):
        """Verify that cumulative product is applied correctly."""
        dates = pd.date_range("2025-01-02", periods=3, freq="D")
        df = pd.DataFrame({
            "nav_date": dates,
            "weighted_port_ret": [0.10, 0.05, -0.02],
            "weighted_bench_ret": [0.08, 0.03, -0.01],
        })
        port, bench = _build_composite_from_returns(df)
        # port: 100 * 1.10 = 110.0, 110 * 1.05 = 115.5, 115.5 * 0.98 = 113.19
        assert pytest.approx(port.iloc[1], rel=1e-4) == 110.0
        assert pytest.approx(port.iloc[2], rel=1e-4) == 115.5
        assert pytest.approx(port.iloc[3], rel=1e-4) == 113.19

    def test_empty_dataframe_returns_empty_series(self):
        empty = pd.DataFrame(columns=["nav_date", "weighted_port_ret", "weighted_bench_ret"])
        port, bench = _build_composite_from_returns(empty)
        assert len(port) == 0
        assert len(bench) == 0

    def test_single_row(self):
        """Single return row should produce 2-element series (base + 1 day)."""
        dates = pd.date_range("2025-06-01", periods=1, freq="D")
        df = pd.DataFrame({
            "nav_date": dates,
            "weighted_port_ret": [0.05],
            "weighted_bench_ret": [0.03],
        })
        port, bench = _build_composite_from_returns(df)
        assert len(port) == 2
        assert port.iloc[0] == 100.0
        assert pytest.approx(port.iloc[1], rel=1e-4) == 105.0

    def test_zero_returns_stay_at_100(self):
        dates = pd.date_range("2025-01-02", periods=4, freq="D")
        df = pd.DataFrame({
            "nav_date": dates,
            "weighted_port_ret": [0.0, 0.0, 0.0, 0.0],
            "weighted_bench_ret": [0.0, 0.0, 0.0, 0.0],
        })
        port, bench = _build_composite_from_returns(df)
        for val in port:
            assert pytest.approx(val, rel=1e-6) == 100.0


# ── _apply_range_filter tests ──


class TestApplyRangeFilter:
    def test_all_range_returns_full_df(self, sample_agg_df):
        result = _apply_range_filter(sample_agg_df, "ALL")
        assert len(result) == len(sample_agg_df)

    def test_1m_filter(self, sample_agg_df):
        result = _apply_range_filter(sample_agg_df, "1M")
        latest = sample_agg_df["nav_date"].iloc[-1]
        cutoff = latest - pd.Timedelta(days=30)
        assert result["nav_date"].iloc[0] >= cutoff

    def test_1y_filter(self, sample_agg_df):
        result = _apply_range_filter(sample_agg_df, "1Y")
        latest = sample_agg_df["nav_date"].iloc[-1]
        cutoff = latest - pd.Timedelta(days=365)
        assert result["nav_date"].iloc[0] >= cutoff

    def test_case_insensitive(self, sample_agg_df):
        r1 = _apply_range_filter(sample_agg_df, "3m")
        r2 = _apply_range_filter(sample_agg_df, "3M")
        assert len(r1) == len(r2)

    def test_empty_df_returns_empty(self):
        empty = pd.DataFrame(columns=["nav_date", "total_aum"])
        result = _apply_range_filter(empty, "1M")
        assert len(result) == 0

    def test_unknown_range_returns_full(self, sample_agg_df):
        """Unknown range key should return full dataset (no filtering)."""
        result = _apply_range_filter(sample_agg_df, "UNKNOWN")
        assert len(result) == len(sample_agg_df)


# ── TWR corpus-adjustment regression tests ────────────────────────────────
#
# The production SQL in aggregate_service._fetch_daily_composite_returns
# computes per-client daily returns adjusted for corpus inflows BEFORE the
# AUM-weighted aggregation. The previous (buggy) SQL used the naive
# ``(nav_value - prev_nav) / prev_nav`` formula, which counted every infusion
# day as a giant positive return. Across 364 clients with many infusions over
# 5+ years this compounded to an absurd +625% aggregate Since-Inception.
#
# These tests run the actual production SQL (extracted verbatim from
# aggregate_service.py) against an in-memory SQLite database with synthetic
# data, asserting the adjustment behaves correctly on:
#   - Single-day infusion events (test_aggregate_daily_return_ignores_infusion_day)
#   - Multi-month cumulative compounding with mid-period infusions
#     (test_aggregate_cumulative_return_plausible)


# Verbatim copy of the SQL in aggregate_service._fetch_daily_composite_returns,
# rewritten only to use SQLite-compatible boolean literals (1/0 instead of
# true/false) and to drop the JOIN to cpp_clients (synthetic data assumes all
# rows belong to active non-admin clients — the JOIN is incidental to the
# TWR math). Keeping this string explicit guards the SQL math against drift.
# Partition is by portfolio_id (NOT client_id): a merged client owns several
# portfolios, and partitioning by client_id interleaves their NAVs.
_TWR_COMPOSITE_SQL = """
    WITH client_nav AS (
        SELECT
            n.nav_date,
            n.portfolio_id,
            n.nav_value,
            n.invested_amount,
            COALESCE(n.benchmark_value, 0) AS benchmark_value,
            LAG(n.nav_value) OVER (
                PARTITION BY n.portfolio_id ORDER BY n.nav_date
            ) AS prev_nav,
            LAG(n.invested_amount) OVER (
                PARTITION BY n.portfolio_id ORDER BY n.nav_date
            ) AS prev_invested,
            LAG(COALESCE(n.benchmark_value, 0)) OVER (
                PARTITION BY n.portfolio_id ORDER BY n.nav_date
            ) AS prev_bench
        FROM cpp_nav_series n
        WHERE n.nav_value > 0
    ),
    daily_rets AS (
        SELECT
            nav_date,
            prev_nav,
            (nav_value /
                (prev_nav + (invested_amount - prev_invested))
            ) - 1.0 AS port_ret,
            CASE WHEN prev_bench > 0
                 THEN (benchmark_value - prev_bench) / prev_bench
                 ELSE 0 END AS bench_ret
        FROM client_nav
        WHERE prev_nav > 0
          AND prev_invested IS NOT NULL
          AND (prev_nav + (invested_amount - prev_invested)) > 0
    )
    SELECT
        nav_date,
        SUM(prev_nav * port_ret) / SUM(prev_nav) AS weighted_port_ret,
        SUM(prev_nav * bench_ret) / SUM(prev_nav) AS weighted_bench_ret
    FROM daily_rets
    GROUP BY nav_date
    ORDER BY nav_date
"""


def _make_sqlite_with_nav_rows(rows: list[dict]) -> sqlite3.Connection:
    """Create an in-memory SQLite DB with cpp_nav_series + inserted rows.

    ``rows`` is a list of dicts each with keys:
        client_id, nav_date (date), nav_value, invested_amount,
        benchmark_value (optional, default 0)
    """
    conn = sqlite3.connect(":memory:")
    conn.execute("""
        CREATE TABLE cpp_nav_series (
            client_id INTEGER NOT NULL,
            portfolio_id INTEGER NOT NULL,
            nav_date TEXT NOT NULL,
            nav_value REAL NOT NULL,
            invested_amount REAL NOT NULL,
            benchmark_value REAL
        )
    """)
    conn.executemany(
        "INSERT INTO cpp_nav_series "
        "(client_id, portfolio_id, nav_date, nav_value, invested_amount, benchmark_value) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        [
            (
                r["client_id"],
                # Default one portfolio per client (pre-merge shape) unless the
                # test explicitly models a multi-portfolio (merged) client.
                r.get("portfolio_id", r["client_id"]),
                r["nav_date"].isoformat(),
                r["nav_value"],
                r["invested_amount"],
                r.get("benchmark_value", 0.0),
            )
            for r in rows
        ],
    )
    conn.commit()
    return conn


def _run_composite_sql(conn: sqlite3.Connection) -> pd.DataFrame:
    """Execute the production TWR SQL against the given SQLite connection."""
    cur = conn.execute(_TWR_COMPOSITE_SQL)
    rows = cur.fetchall()
    return pd.DataFrame(
        rows, columns=["nav_date", "weighted_port_ret", "weighted_bench_ret"],
    )


class TestTwrCorpusAdjustment:
    def test_aggregate_daily_return_ignores_infusion_day(self):
        """An infusion day must not show up as a giant positive daily return.

        Synthetic scenario for a single client:
          Day 1: NAV = 100K, corpus = 100K  (anchor; no prev row)
          Day 2: NAV = 102K, corpus = 100K  (true +2% market move, no infusion)
          Day 3: NAV = 152K, corpus = 150K  (+50K infusion + true ~-1.96% market move)

        Naive return on Day 3 would be (152 - 102) / 102 = +49.02% — that's
        almost entirely capital inflow, not market performance.

        TWR-adjusted return:
            adjusted_prev = 102 + (150 - 100) = 152
            ret = 152 / 152 - 1 = 0.0  (flat, which is the truth — the new ₹50K
                                       hit the books at the same NAV)
        """
        d1, d2, d3 = date(2025, 1, 1), date(2025, 1, 2), date(2025, 1, 3)
        rows = [
            {"client_id": 1, "nav_date": d1, "nav_value": 100_000, "invested_amount": 100_000},
            {"client_id": 1, "nav_date": d2, "nav_value": 102_000, "invested_amount": 100_000},
            {"client_id": 1, "nav_date": d3, "nav_value": 152_000, "invested_amount": 150_000},
        ]
        conn = _make_sqlite_with_nav_rows(rows)
        out = _run_composite_sql(conn)

        # Two rows: day 2 (normal day) and day 3 (infusion day).
        assert len(out) == 2

        # Day 2: normal +2% return.
        day2 = out[out["nav_date"] == d2.isoformat()].iloc[0]
        assert day2["weighted_port_ret"] == pytest.approx(0.02, rel=1e-4)

        # Day 3: TWR-adjusted should be ~0%, NOT +49.02% (naive bug).
        day3 = out[out["nav_date"] == d3.isoformat()].iloc[0]
        assert day3["weighted_port_ret"] == pytest.approx(0.0, abs=1e-6)
        assert day3["weighted_port_ret"] < 0.05  # Sanity: definitely not 49%.

    def test_aggregate_daily_return_two_clients_aum_weighted(self):
        """AUM weighting (by prev_nav) is preserved across clients.

        Client 1 (small): prev_nav 100K, today +1%
        Client 2 (large): prev_nav 900K, today receives 100K infusion at flat NAV

        Expected weighted return:
          client1 ret = +0.01,                 weight = 100K
          client2 ret = 0.0 (TWR-adjusted),    weight = 900K
          weighted   = (100K * 0.01 + 900K * 0.0) / (100K + 900K) = 0.001
        """
        d1, d2 = date(2025, 6, 1), date(2025, 6, 2)
        rows = [
            # Client 1: simple +1% move, no corpus change
            {"client_id": 1, "nav_date": d1, "nav_value": 100_000, "invested_amount": 100_000},
            {"client_id": 1, "nav_date": d2, "nav_value": 101_000, "invested_amount": 100_000},
            # Client 2: 100K infusion, NAV moves from 900K to 1M (all infusion)
            {"client_id": 2, "nav_date": d1, "nav_value": 900_000, "invested_amount": 500_000},
            {"client_id": 2, "nav_date": d2, "nav_value": 1_000_000, "invested_amount": 600_000},
        ]
        conn = _make_sqlite_with_nav_rows(rows)
        out = _run_composite_sql(conn)

        assert len(out) == 1
        weighted = out.iloc[0]["weighted_port_ret"]
        # 100K * 0.01 + 900K * 0.0 = 1000; divide by 1M total prev_nav = 0.001
        assert weighted == pytest.approx(0.001, rel=1e-4)

    def test_aggregate_cumulative_return_plausible(self):
        """Cumulative compounding over many days with a mid-period infusion.

        Single client, 12 monthly observations:
          Month 0:  NAV = 100,  corpus = 100        (anchor)
          Months 1-5:  NAV grows ~1% per month, no infusion
          Month 6: NAV jumps by +50 ON TOP OF its growth, corpus 100 → 150 (infusion)
          Months 7-12: continues growing ~1% per month

        True market return ≈ (1.01)^12 - 1 ≈ +12.68%. With the standard TWR
        convention (treat the cash flow as present for the full day's market
        move), the month-6 ratio is 156.15/155.10 - 1 ≈ +0.68% instead of the
        ideal +1%, so the chained TWR cumulative lands near +12.32%.

        The naive (buggy) cumulative would compound a ~+45% jump on month 6
        (the infusion-as-return) on top of 11 months of +1% growth — landing
        somewhere north of +60%. We assert <20% to keep the regression guard
        broad enough to survive minor numerical drift but tight enough to
        catch any reappearance of the infusion-as-return bug.
        """
        d0 = date(2025, 1, 1)
        rows = []
        nav = 100.0
        corpus = 100.0
        for m in range(13):
            # Grow NAV by ~1% before potential infusion
            if m > 0:
                nav *= 1.01
            # Apply infusion on month 6
            if m == 6:
                nav += 50.0
                corpus += 50.0
            rows.append({
                "client_id": 1,
                "nav_date": d0 + timedelta(days=30 * m),
                "nav_value": nav,
                "invested_amount": corpus,
            })

        conn = _make_sqlite_with_nav_rows(rows)
        out = _run_composite_sql(conn)

        # Chain-link the per-day returns into a cumulative TWR return
        cumulative_ret = float(np.prod(1.0 + out["weighted_port_ret"].values)) - 1.0

        # Expected ~+12.32% under standard TWR convention; naive bug would
        # land >+50% (infusion counted as a return).
        assert cumulative_ret == pytest.approx(0.1232, abs=0.005), (
            f"Expected ~+12.32%, got {cumulative_ret * 100:.2f}% — "
            "TWR adjustment likely regressed."
        )
        assert cumulative_ret < 0.20, (
            f"Cumulative return {cumulative_ret * 100:.2f}% is implausibly high — "
            "infusion is being double-counted as return."
        )

    def test_aggregate_skips_first_row_per_client(self):
        """The first NAV row per client has no prev_invested — must be excluded."""
        d1, d2 = date(2025, 3, 1), date(2025, 3, 2)
        rows = [
            {"client_id": 1, "nav_date": d1, "nav_value": 100_000, "invested_amount": 100_000},
            {"client_id": 1, "nav_date": d2, "nav_value": 101_000, "invested_amount": 100_000},
        ]
        conn = _make_sqlite_with_nav_rows(rows)
        out = _run_composite_sql(conn)
        # Only the day-2 row should appear (day 1 has no prev row)
        assert len(out) == 1
        assert out.iloc[0]["nav_date"] == d2.isoformat()

    def test_aggregate_handles_withdrawal_day(self):
        """Symmetric case: a partial withdrawal should also not register as a return.

        Day 1: NAV = 200K, corpus = 200K
        Day 2: NAV = 150K, corpus = 150K  (₹50K withdrawn at flat per-unit value)

        Naive: (150 - 200)/200 = -25% (looks like a market crash)
        TWR-adjusted: adjusted_prev = 200 + (150 - 200) = 150
                      ret = 150/150 - 1 = 0.0  (correct — no market move)
        """
        d1, d2 = date(2025, 4, 1), date(2025, 4, 2)
        rows = [
            {"client_id": 1, "nav_date": d1, "nav_value": 200_000, "invested_amount": 200_000},
            {"client_id": 1, "nav_date": d2, "nav_value": 150_000, "invested_amount": 150_000},
        ]
        conn = _make_sqlite_with_nav_rows(rows)
        out = _run_composite_sql(conn)
        assert len(out) == 1
        assert out.iloc[0]["weighted_port_ret"] == pytest.approx(0.0, abs=1e-6)

    def test_multi_portfolio_client_not_interleaved(self):
        """Post-merge regression: one client owning several portfolios must have
        each sleeve's daily return computed within its OWN NAV series.

        The LAG windows partition by portfolio_id. If they (wrongly) partition by
        client_id, the merged client's two sleeves interleave — a ₹5,000 sleeve's
        row takes the ₹1,000 sleeve's row as "yesterday" → daily returns of
        +400% / -80% instead of the true ~+1%. This produced the −92% CAGR /
        −100% drawdown / +26,935% month seen on the live admin dashboard.

        Both sleeves: flat corpus (no infusions), steady +1%/day. Client 1 owns
        portfolio 10 (₹5,000 base) and portfolio 11 (₹1,000 base).
        """
        dates = [date(2025, 3, 3) + timedelta(days=i) for i in range(5)]
        rows = []
        for i, d in enumerate(dates):
            rows.append({"client_id": 1, "portfolio_id": 10, "nav_date": d,
                         "nav_value": 5000.0 + 50.0 * i, "invested_amount": 1000.0})
        for i, d in enumerate(dates):
            rows.append({"client_id": 1, "portfolio_id": 11, "nav_date": d,
                         "nav_value": 1000.0 + 10.0 * i, "invested_amount": 1000.0})

        conn = _make_sqlite_with_nav_rows(rows)
        out = _run_composite_sql(conn)

        # 4 return days (5 NAV points − the excluded first row per portfolio).
        assert len(out) == 4, (
            f"expected 4 return days, got {len(out)} — sleeves interleaved "
            "(LAG must partition by portfolio_id, not client_id)"
        )
        rets = out["weighted_port_ret"].astype(float)
        # Every day's AUM-weighted return is ~+1%; interleaving would blow far
        # outside this band (±hundreds of %).
        assert rets.between(0.005, 0.02).all(), (
            f"implausible daily returns {rets.tolist()} — the merged client's "
            "sleeves are being interleaved; partition by portfolio_id"
        )
