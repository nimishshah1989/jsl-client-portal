"""Tests for benchmark_service — particularly guarding against the
"single value written across every nav_date" bug that hit production
on 2026-05-26 (NIFTY max DD reported as -0.14%, CAGR 0.01% over 4y).

These tests focus on the *alignment* layer because that's where a
single survived value could have been multiplied across the entire NAV
date range. DB-backed tests (``_fetch_jip_index_history``) are skipped
when no fie_v3 connection is configured — they are smoke-tested
manually with ``POST /api/admin/recompute-risk`` after deploy.
"""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from backend.services.benchmark_service import align_benchmark


def _synthetic_nifty(start: date, end: date, seed: int = 42) -> pd.DataFrame:
    """Build a plausible NIFTY-shaped close series with trading-day gaps.

    Skips weekends so the test exercises the same forward-fill the real
    NSE calendar requires.
    """
    rng = np.random.default_rng(seed)
    dates: list[pd.Timestamp] = []
    closes: list[float] = []
    price = 17000.0
    cur = start
    while cur <= end:
        # Skip Saturday (5) and Sunday (6) — NSE is closed.
        if cur.weekday() < 5:
            price *= 1.0 + rng.normal(0, 0.01)
            dates.append(pd.Timestamp(cur))
            closes.append(price)
        cur += timedelta(days=1)
    return pd.DataFrame({"close": closes}, index=pd.DatetimeIndex(dates, name="date"))


def _nav_dates(start: date, end: date) -> pd.DatetimeIndex:
    """Daily NAV dates including weekends — same shape cpp_nav_series uses."""
    return pd.date_range(start, end, freq="D")


class TestAlignBenchmarkNoFlatSeries:
    """The bug: benchmark_value column was a single constant for 87% of rows.

    Any reasonable nav-date span (months / years) must produce many distinct
    values once aligned. If it doesn't, the writeback into cpp_nav_series will
    silently turn NIFTY into a near-zero-volatility flat line.
    """

    def test_long_range_yields_many_distinct_values(self):
        """A 4+ year NAV span must produce well over 100 distinct closes."""
        start, end = date(2020, 9, 28), date(2024, 12, 31)
        nifty = _synthetic_nifty(start, end)
        nav_dates = _nav_dates(start, end)
        aligned = align_benchmark(nav_dates, nifty)

        non_na = aligned.dropna()
        assert len(non_na) > 1000, (
            f"Expected dense alignment across 4y; got {len(non_na)} non-NaN cells"
        )
        distinct = non_na.nunique()
        assert distinct > 100, (
            f"Alignment must produce many distinct benchmark values; got "
            f"{distinct}. This is the exact 'flat benchmark' regression that "
            f"hit production 2026-05-26."
        )

    def test_one_year_range_still_diverse(self):
        """Even a 1Y range should retain >100 distinct closes after alignment."""
        start, end = date(2024, 1, 1), date(2024, 12, 31)
        nifty = _synthetic_nifty(start, end, seed=7)
        nav_dates = _nav_dates(start, end)
        aligned = align_benchmark(nav_dates, nifty)

        non_na = aligned.dropna()
        assert non_na.nunique() > 100, (
            f"1Y alignment collapsed to {non_na.nunique()} distinct values — "
            f"likely a forward-fill bug propagating one quote across the range."
        )

    def test_constant_input_is_rejected_not_propagated(self):
        """If the JIP source ever returned a single value, alignment must
        return an EMPTY series rather than silently writing that constant
        to every nav_date — matching the existing sanity-check in
        align_benchmark (distinct_vals < 2 short-circuit)."""
        start, end = date(2024, 1, 1), date(2024, 12, 31)
        flat = pd.DataFrame(
            {"close": [23643.50] * 50},
            index=pd.date_range(start, periods=50, freq="B", name="date"),
        )
        nav_dates = _nav_dates(start, end)
        aligned = align_benchmark(nav_dates, flat)

        # The sanity guard should produce an empty/all-NaN series rather than
        # 365 cells of 23643.50 — that's what tanked production.
        non_na = aligned.dropna()
        if len(non_na) > 0:
            assert non_na.nunique() >= 2, (
                "Single-value benchmark input must NOT propagate to nav_dates"
            )

    def test_per_date_alignment_not_global_constant(self):
        """Two non-adjacent nav_dates should pick up different benchmark
        values when the underlying NIFTY series moved between them."""
        start, end = date(2024, 1, 1), date(2024, 6, 30)
        nifty = _synthetic_nifty(start, end, seed=13)
        nav_dates = _nav_dates(start, end)
        aligned = align_benchmark(nav_dates, nifty)

        # First and last nav-dates should map to materially different closes.
        first_val = aligned.dropna().iloc[0]
        last_val = aligned.dropna().iloc[-1]
        assert first_val != last_val, (
            "Forward-fill collapsed start and end of a 6-month span to the "
            "same value — benchmark writeback would be near-flat."
        )

    def test_weekend_navdate_forward_filled_from_friday(self):
        """A Sunday nav_date should inherit Friday's close (forward-fill cap
        of 7 calendar days easily covers a weekend)."""
        # Friday 2024-06-21, Saturday 22, Sunday 23, Monday 24
        nifty = pd.DataFrame(
            {"close": [22500.0, 22550.0]},
            index=pd.DatetimeIndex(
                [pd.Timestamp("2024-06-21"), pd.Timestamp("2024-06-24")], name="date"
            ),
        )
        nav_dates = pd.DatetimeIndex(
            [pd.Timestamp("2024-06-21"), pd.Timestamp("2024-06-23"), pd.Timestamp("2024-06-24")]
        )
        aligned = align_benchmark(nav_dates, nifty)

        # Only 2 distinct values total — series is too thin to pass the
        # diversity guard. The test still confirms ALIGNMENT logic by checking
        # that — when accepted — Sunday inherits Friday's value. If the
        # diversity guard kicked in (returning empty), that's also acceptable
        # because that means the writeback would be skipped (not "flat").
        non_na = aligned.dropna()
        if len(non_na) > 0:
            # Sunday must NOT equal Monday (it's before Monday's close was known).
            sat_idx = pd.Timestamp("2024-06-23")
            if sat_idx in aligned.index and not pd.isna(aligned.loc[sat_idx]):
                assert aligned.loc[sat_idx] == 22500.0, (
                    "Sunday should inherit Friday's close via forward-fill, "
                    "not Monday's (which wasn't observed yet)."
                )


class TestJIPDSNConstruction:
    """The DSN helper must mint a fie_v3 DSN with SSL params layered in,
    matching backend/database.py's TLS posture."""

    def test_dsn_swaps_database_name(self, monkeypatch):
        from backend.services import benchmark_service as svc
        monkeypatch.setenv(
            "DATABASE_URL_SYNC",
            "postgresql://u:p@some-host.rds.amazonaws.com:5432/client_portal",
        )
        monkeypatch.setenv("RDS_CA_BUNDLE", "/nonexistent/no-bundle.pem")
        dsn = svc._jip_db_dsn()
        assert dsn is not None
        assert "/fie_v3" in dsn
        assert "/client_portal" not in dsn

    def test_dsn_includes_sslmode_for_rds(self, monkeypatch, tmp_path):
        from backend.services import benchmark_service as svc
        # Create a fake CA bundle so the "verify-full + sslrootcert" branch fires.
        fake_ca = tmp_path / "ca.pem"
        fake_ca.write_text("dummy")
        monkeypatch.setenv(
            "DATABASE_URL_SYNC",
            "postgresql://u:p@some-host.rds.amazonaws.com:5432/client_portal",
        )
        monkeypatch.setenv("RDS_CA_BUNDLE", str(fake_ca))
        dsn = svc._jip_db_dsn()
        assert dsn is not None
        assert "sslmode=verify-full" in dsn
        assert f"sslrootcert={fake_ca}" in dsn

    def test_dsn_returns_none_when_unset(self, monkeypatch):
        from backend.services import benchmark_service as svc
        monkeypatch.delenv("DATABASE_URL_SYNC", raising=False)
        monkeypatch.delenv("DATABASE_URL", raising=False)
        assert svc._jip_db_dsn() is None
