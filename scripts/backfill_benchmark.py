"""One-shot: rewrite cpp_nav_series.benchmark_value using JIP data core NIFTY history.

Ingestion previously populated benchmark_value from yfinance during an interval
when the API returned only a short window, so most rows were forward-filled
with a single recent Nifty close.  This script pulls the full daily series from
fie_v3.public.index_prices (index_name='NIFTY') and updates every row.

Safe to re-run (idempotent): each row is set to today's JIP close for its date,
using forward-fill for weekends/holidays.
"""
import os
import sys
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

import pandas as pd
import psycopg2
from psycopg2.extras import execute_values


def _dsn(dbname: str) -> str:
    url = os.getenv("DATABASE_URL_SYNC") or os.getenv("DATABASE_URL", "")
    url = url.replace("postgresql+asyncpg://", "postgresql://")
    base = url.split("?")[0].rsplit("/", 1)[0] + f"/{dbname}"
    query = "?" + url.split("?", 1)[1] if "?" in url else ""
    return base + query


def load_nifty() -> pd.DataFrame:
    conn = psycopg2.connect(_dsn("fie_v3"))
    try:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT date, close_price FROM public.index_prices
                   WHERE index_name='NIFTY' ORDER BY date ASC"""
            )
            rows = cur.fetchall()
    finally:
        conn.close()
    df = pd.DataFrame(rows, columns=["date", "close"])
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date").sort_index()
    df["close"] = pd.to_numeric(df["close"], errors="coerce")
    return df.dropna()


def backfill() -> None:
    nifty = load_nifty()
    print(f"JIP NIFTY: {len(nifty)} rows, {nifty.index.min().date()} → {nifty.index.max().date()}")

    conn = psycopg2.connect(_dsn("client_portal"))
    conn.autocommit = False
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT DISTINCT nav_date FROM cpp_nav_series ORDER BY nav_date ASC"
            )
            nav_dates = [r[0] for r in cur.fetchall()]
        print(f"cpp_nav_series distinct dates: {len(nav_dates)} "
              f"({nav_dates[0]} → {nav_dates[-1]})")

        # Build a full date index covering nav_dates range and forward-fill
        full = pd.date_range(min(nav_dates), max(nav_dates), freq="D")
        aligned = nifty.reindex(full, method="ffill").bfill()

        # Map each nav_date to its aligned Nifty close
        lookup = {d: float(aligned.loc[pd.Timestamp(d), "close"]) for d in nav_dates}

        # Bulk update
        with conn.cursor() as cur:
            updates = [(Decimal(f"{v:.6f}"), d) for d, v in lookup.items()]
            cur.executemany(
                "UPDATE cpp_nav_series SET benchmark_value=%s WHERE nav_date=%s",
                updates,
            )
            affected = cur.rowcount
        conn.commit()
        print(f"Updated {affected} rows across {len(nav_dates)} dates.")

        # Sanity check
        with conn.cursor() as cur:
            cur.execute(
                """SELECT COUNT(DISTINCT benchmark_value), MIN(benchmark_value),
                          MAX(benchmark_value)
                   FROM cpp_nav_series"""
            )
            print("Post-backfill stats:", cur.fetchone())
    finally:
        conn.close()


if __name__ == "__main__":
    backfill()
