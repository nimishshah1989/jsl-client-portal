"""Regression tests for the self-healing benchmark pipeline.

These cover the 2026-05-26 production incident where a NAV upload for 277
clients on a single date wrote benchmark_value=0 because the pre-fetched
Nifty window was too narrow to align against the client's full nav_dates
history. The aggregate page then computed a daily benchmark return of
``(0 − 23654.70) / 23654.70 = -100%``.

Tests:

  1. ``test_ingest_fills_bench_from_fie_v3``
     mock fie_v3 returning Nifty for the upload date,
     assert post-ingest the bench column is set on the cpp_nav_series row.

  2. ``test_ingest_falls_back_to_yfinance_when_fie_v3_missing``
     mock fie_v3 with empty result, mock yfinance with a value,
     assert the value lands on the row AND that the fallback wrote it back
     to fie_v3.

  3. ``test_nightly_sweep_fills_holes``
     insert 3 nav rows with bench=0, mock fie_v3 with Nifty for the same
     dates, call the sweep function, assert all 3 rows now have non-zero
     bench.

  4. ``test_sweep_logs_failure_when_no_source_has_date``
     insert 1 nav row with bench=0 for date X, mock both fie_v3 AND
     yfinance returning empty for X, call sweep, assert the row stays at 0
     but a warning is logged.
"""

from __future__ import annotations

import datetime as dt
import logging
import os
from decimal import Decimal

# Env vars must be set BEFORE importing backend modules.
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("JWT_SECRET", "t" * 64)
os.environ.setdefault("APP_ENV", "development")

import pandas as pd
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from backend.database import Base
from backend.models.client import Client
from backend.models.nav_series import NavSeries
from backend.models.portfolio import Portfolio


# ── Test infrastructure: in-memory SQLite ─────────────────────────────────


@pytest_asyncio.fixture(scope="function")
async def db_engine():
    """Per-test in-memory SQLite with the three tables this suite touches."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    tables = [Client.__table__, Portfolio.__table__, NavSeries.__table__]
    async with engine.begin() as conn:
        await conn.run_sync(lambda c: Base.metadata.create_all(c, tables=tables))
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest_asyncio.fixture(scope="function")
async def session_factory(db_engine):
    return async_sessionmaker(bind=db_engine, expire_on_commit=False)


# ── Cache helper: every test must start with a clean BenchmarkCache so
#    one test's seeded data doesn't leak into the next ──


@pytest.fixture(autouse=True)
def _clear_bench_cache():
    from backend.services.benchmark_service import BenchmarkCache
    BenchmarkCache.clear()
    yield
    BenchmarkCache.clear()


# ── Data seeding helpers ──────────────────────────────────────────────────


async def _seed_client_with_nav(
    session_factory,
    *,
    nav_rows: list[tuple[dt.date, Decimal | None]],
) -> tuple[int, int]:
    """Create one client + portfolio + the given nav_rows.

    ``nav_rows`` is a list of (nav_date, benchmark_value) — benchmark_value
    can be None or 0 to represent a hole.
    """
    async with session_factory() as session:
        client = Client(
            client_code="TEST001",
            name="Test Client",
            username="testclient",
            password_hash="$2b$12$dummyhashvaluemorethanenoughforbcrypt",
            is_active=True,
            is_admin=False,
        )
        session.add(client)
        await session.flush()

        portfolio = Portfolio(
            client_id=client.id,
            portfolio_name="PMS Equity",
            benchmark="NIFTY500",
            inception_date=nav_rows[0][0],
            status="active",
        )
        session.add(portfolio)
        await session.flush()

        for nav_date, bench in nav_rows:
            session.add(
                NavSeries(
                    client_id=client.id,
                    portfolio_id=portfolio.id,
                    nav_date=nav_date,
                    nav_value=Decimal("1000000.00"),
                    invested_amount=Decimal("1000000.00"),
                    current_value=Decimal("1000000.00"),
                    benchmark_value=bench,
                    cash_pct=Decimal("0"),
                )
            )

        await session.commit()
        return client.id, portfolio.id


# ── Test 1: pre-fetched fie_v3 data covers upload → bench lands on row ───


class TestIngestFillsBenchFromFieV3:
    """Direct test of update_benchmark_values — when the bulk pre-fetch
    covers the client's full nav_dates range, the row's bench gets set."""

    @pytest.mark.asyncio
    async def test_ingest_fills_bench_from_fie_v3(
        self, session_factory, monkeypatch
    ):
        from backend.services import benchmark_service, ingestion_helpers

        # The client already has 30 days of history; the upload's new date is
        # 2026-05-26. The pre-fetched bench DataFrame covers the full range.
        history_dates = [dt.date(2026, 4, 27) + dt.timedelta(days=i) for i in range(30)]
        # Seed past rows WITH benchmarks (the historical sweep already filled
        # them); the LAST date is the just-uploaded one with bench=None.
        rows = [(d, Decimal("23000")) for d in history_dates[:-1]]
        rows.append((history_dates[-1], None))
        client_id, portfolio_id = await _seed_client_with_nav(
            session_factory, nav_rows=rows
        )

        # Mock fie_v3 to return distinct closes across the full range — so
        # align_benchmark's diversity guard is satisfied.
        def fake_jip(name, start, end):
            dates = pd.date_range(start, end, freq="B")
            closes = [23000.0 + i * 5 for i in range(len(dates))]
            return pd.DataFrame({"close": closes}, index=pd.DatetimeIndex(dates))

        monkeypatch.setattr(
            benchmark_service, "_fetch_jip_index_history", fake_jip
        )

        # yfinance must NOT be called — fie_v3 covers everything.
        def explode_yf(*args, **kwargs):
            raise AssertionError("yfinance should not be called when fie_v3 covers range")

        monkeypatch.setattr(
            benchmark_service, "_fetch_yfinance_history", explode_yf
        )

        # Pre-fetched DataFrame just for the upload date (matches the
        # production ingestion pattern that triggered the incident).
        upload_date = history_dates[-1]
        pre_fetched = benchmark_service.fetch_nifty_data(upload_date, upload_date)

        async with session_factory() as session:
            count = await ingestion_helpers.update_benchmark_values(
                session, client_id, portfolio_id, benchmark_data=pre_fetched,
            )
            await session.commit()

            # The just-uploaded row must have a non-zero, non-NULL bench.
            from sqlalchemy import select
            result = await session.execute(
                select(NavSeries.benchmark_value).where(
                    NavSeries.client_id == client_id,
                    NavSeries.nav_date == upload_date,
                )
            )
            bench = result.scalar_one()

        assert count >= 1, "Expected at least the upload date to be updated"
        assert bench is not None, "Upload-date bench must not be NULL"
        assert bench != 0, (
            "Upload-date bench must not be 0 — that was the 2026-05-26 bug"
        )


# ── Test 2: fie_v3 empty → yfinance fallback + write-back ─────────────────


class TestIngestFallsBackToYFinance:
    """When fie_v3 returns nothing for the requested date, yfinance fills
    the gap AND we write the value back to fie_v3 so we don't re-fetch."""

    @pytest.mark.asyncio
    async def test_ingest_falls_back_to_yfinance_when_fie_v3_missing(
        self, session_factory, monkeypatch
    ):
        from backend.services import benchmark_service, ingestion_helpers

        # Seed a 30-day window of past rows with bench set, and the latest
        # date with bench missing.
        history_dates = [dt.date(2026, 4, 27) + dt.timedelta(days=i) for i in range(30)]
        rows = [(d, Decimal("23000")) for d in history_dates[:-1]]
        rows.append((history_dates[-1], None))
        client_id, portfolio_id = await _seed_client_with_nav(
            session_factory, nav_rows=rows
        )

        upload_date = history_dates[-1]

        # fie_v3 returns NO rows — simulates a date that hasn't been ingested.
        def empty_jip(name, start, end):
            return pd.DataFrame(columns=["close"])

        monkeypatch.setattr(
            benchmark_service, "_fetch_jip_index_history", empty_jip
        )

        # yfinance returns data covering history + the upload date with
        # distinct closes (so align_benchmark's diversity guard passes).
        def fake_yf(start, end):
            dates = pd.date_range(start, end - dt.timedelta(days=1), freq="B")
            closes = [23000.0 + i * 5 for i in range(len(dates))]
            return pd.DataFrame(
                {"Close": closes}, index=pd.DatetimeIndex(dates)
            )

        monkeypatch.setattr(
            benchmark_service, "_fetch_yfinance_history", fake_yf
        )

        # Capture write-back calls so we can prove the yfinance result was
        # persisted to fie_v3.
        writeback_calls: list[pd.DataFrame] = []

        def capture_writeback(name, df):
            writeback_calls.append(df.copy())
            return len(df)

        monkeypatch.setattr(
            benchmark_service, "_write_jip_index_history", capture_writeback
        )

        pre_fetched = benchmark_service.fetch_nifty_data(upload_date, upload_date)

        async with session_factory() as session:
            await ingestion_helpers.update_benchmark_values(
                session, client_id, portfolio_id, benchmark_data=pre_fetched,
            )
            await session.commit()

            from sqlalchemy import select
            result = await session.execute(
                select(NavSeries.benchmark_value).where(
                    NavSeries.client_id == client_id,
                    NavSeries.nav_date == upload_date,
                )
            )
            bench = result.scalar_one()

        assert bench is not None and bench != 0, (
            f"yfinance fallback failed to populate bench: {bench!r}"
        )
        # The write-back is critical: every yfinance fetch should hydrate
        # the canonical fie_v3 cache so we don't keep re-fetching.
        assert len(writeback_calls) > 0, (
            "yfinance result must be written back to fie_v3.index_prices"
        )
        assert any(not df.empty for df in writeback_calls), (
            "Write-back must include at least one row"
        )


# ── Test 3: nightly sweep fills 3 holes ───────────────────────────────────


class TestNightlySweepFillsHoles:
    @pytest.mark.asyncio
    async def test_nightly_sweep_fills_holes(self, session_factory, monkeypatch):
        from backend.services import benchmark_service, benchmark_sweep

        today = dt.date(2026, 5, 26)
        hole_dates = [today - dt.timedelta(days=i) for i in (0, 1, 2)]
        # All three holes have bench=0 (the production-incident shape).
        rows = [(d, Decimal("0")) for d in sorted(hole_dates)]
        await _seed_client_with_nav(session_factory, nav_rows=rows)

        # Mock fie_v3 to return distinct closes for the hole dates.
        def fake_jip(name, start, end):
            dates = pd.date_range(start, end, freq="D")
            closes = [23000.0 + i * 10 for i in range(len(dates))]
            return pd.DataFrame({"close": closes}, index=pd.DatetimeIndex(dates))

        monkeypatch.setattr(
            benchmark_service, "_fetch_jip_index_history", fake_jip
        )
        # yfinance must NOT be invoked when fie_v3 covers the range.
        monkeypatch.setattr(
            benchmark_service, "_fetch_yfinance_history",
            lambda *a, **k: (_ for _ in ()).throw(
                AssertionError("yfinance should not be called when fie_v3 covers range")
            ),
        )

        async with session_factory() as session:
            result = await benchmark_sweep.sweep_benchmark_holes(
                session, days=14, today=today
            )

            from sqlalchemy import select
            res = await session.execute(
                select(NavSeries.nav_date, NavSeries.benchmark_value).order_by(
                    NavSeries.nav_date
                )
            )
            stored = list(res.fetchall())

        assert result.dates_checked == 3
        assert result.dates_filled == 3
        assert result.dates_failed == 0
        assert result.rows_updated == 3, (
            f"Expected 3 rows updated, got {result.rows_updated}"
        )
        for nav_date, bench in stored:
            assert bench is not None, f"{nav_date} still NULL"
            assert bench != 0, f"{nav_date} still 0 after sweep"


# ── Test 4: sweep logs failure when no source has the date ────────────────


class TestSweepLogsFailureWhenNoSource:
    @pytest.mark.asyncio
    async def test_sweep_logs_failure_when_no_source_has_date(
        self, session_factory, monkeypatch, caplog
    ):
        from backend.services import benchmark_service, benchmark_sweep

        today = dt.date(2026, 5, 26)
        hole = today  # one hole on today
        rows = [(hole, Decimal("0"))]
        await _seed_client_with_nav(session_factory, nav_rows=rows)

        # Both sources return empty.
        monkeypatch.setattr(
            benchmark_service, "_fetch_jip_index_history",
            lambda *a, **k: pd.DataFrame(columns=["close"]),
        )

        def empty_yf(start, end):
            # Return an empty hist; _fetch_yfinance_history raises if empty,
            # so emulate that to exercise the "yfinance also returns nothing"
            # branch.
            raise RuntimeError("yfinance returned no data (test)")

        monkeypatch.setattr(
            benchmark_service, "_fetch_yfinance_history", empty_yf
        )
        monkeypatch.setattr(
            benchmark_service, "_write_jip_index_history",
            lambda *a, **k: 0,
        )

        caplog.set_level(logging.WARNING, logger="backend.services.benchmark_sweep")

        async with session_factory() as session:
            result = await benchmark_sweep.sweep_benchmark_holes(
                session, days=14, today=today
            )

            from sqlalchemy import select
            res = await session.execute(
                select(NavSeries.benchmark_value).where(
                    NavSeries.nav_date == hole
                )
            )
            bench = res.scalar_one()

        # The row stays at 0 (not silently overwritten with garbage).
        assert bench == Decimal("0"), (
            f"Row should stay at 0 when no source has the date, got {bench!r}"
        )
        assert result.dates_failed == 1
        assert result.dates_filled == 0
        assert hole in result.failures

        # A WARNING must mention the failure for ops visibility.
        warnings_text = " ".join(
            r.message for r in caplog.records if r.levelno >= logging.WARNING
        )
        assert "No Nifty close" in warnings_text or "bench-sync" in warnings_text, (
            f"Expected a bench-sync warning; got: {warnings_text!r}"
        )
