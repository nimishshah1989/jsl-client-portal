"""Verify risk metrics against PMS reference HTML files.

Reads NAV data from DB, runs the risk engine in-memory (NO writes),
and prints computed metrics per client. Compare against groundtruth.json.
"""
import os
import sys
import json
import asyncio
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv(os.path.join(sys.path[0], ".env"))

import pandas as pd
from sqlalchemy import text
from backend.database import AsyncSessionLocal
from backend.services.risk_metrics import (
    compute_twr_series,
    compute_weighted_bench_return,
    absolute_return,
    cagr,
)
from backend.services.risk_engine import compute_all_metrics, _RF_RATE
from backend.services.xirr_service import (
    compute_xirr,
    extract_cash_flows_from_corpus,
    extract_cash_flows_from_db,
)


async def run_for_client(client_code: str) -> dict:
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            text("""
                SELECT c.id, p.id, p.inception_date, c.name
                FROM cpp_clients c
                JOIN cpp_portfolios p ON p.client_id = c.id
                WHERE c.client_code = :code
                LIMIT 1
            """),
            {"code": client_code},
        )
        row = result.fetchone()
        if row is None:
            return {"error": f"client {client_code} not found"}
        client_id, portfolio_id, inception, name = row

        nav_result = await db.execute(
            text("""
                SELECT nav_date, nav_value, invested_amount, current_value,
                       benchmark_value, cash_pct,
                       COALESCE(etf_value, 0), COALESCE(cash_value, 0),
                       COALESCE(bank_balance, 0)
                FROM cpp_nav_series
                WHERE client_id = :cid AND portfolio_id = :pid
                ORDER BY nav_date ASC
            """),
            {"cid": client_id, "pid": portfolio_id},
        )
        rows = nav_result.fetchall()
        if not rows:
            return {"error": "no NAV data"}

        nav_df = pd.DataFrame(rows, columns=[
            "nav_date", "nav_value", "invested_amount", "current_value",
            "benchmark_value", "cash_pct", "etf_value", "cash_value", "bank_balance",
        ])
        nav_df["nav_date"] = pd.to_datetime(nav_df["nav_date"])
        for col in ["nav_value", "invested_amount", "current_value", "benchmark_value",
                    "cash_pct", "etf_value", "cash_value", "bank_balance"]:
            nav_df[col] = pd.to_numeric(nav_df[col], errors="coerce").fillna(0)
        nav_df = nav_df.sort_values("nav_date").reset_index(drop=True)

        nav_df["twr_value"] = compute_twr_series(nav_df)

        metrics = compute_all_metrics(nav_df, _RF_RATE)

        weighted_bench = compute_weighted_bench_return(nav_df)
        metrics["bench_return_inception_weighted"] = weighted_bench

        cf_result = await db.execute(
            text("""
                SELECT flow_date, flow_type, amount
                FROM cpp_cash_flows
                WHERE client_id = :cid AND portfolio_id = :pid
                ORDER BY flow_date ASC
            """),
            {"cid": client_id, "pid": portfolio_id},
        )
        cf_rows = cf_result.fetchall()
        terminal_date = nav_df["nav_date"].iloc[-1].to_pydatetime()
        terminal_value = float(nav_df["nav_value"].iloc[-1])
        if cf_rows:
            real_flows = extract_cash_flows_from_db(cf_rows, terminal_date, terminal_value)
            if len(real_flows) >= 2:
                metrics["xirr_from_flows"] = compute_xirr(real_flows)

        xirr_df = pd.DataFrame({
            "date": nav_df["nav_date"],
            "corpus": nav_df["invested_amount"].astype(float),
            "nav": nav_df["nav_value"].astype(float),
        })
        corpus_flows = extract_cash_flows_from_corpus(xirr_df)
        if len(corpus_flows) >= 2:
            metrics["xirr_from_corpus"] = compute_xirr(corpus_flows)

        first_corpus = float(nav_df["invested_amount"].iloc[0])
        last_corpus = float(nav_df["invested_amount"].iloc[-1])
        first_nav = float(nav_df["nav_value"].iloc[0])
        last_nav = float(nav_df["nav_value"].iloc[-1])
        first_bench = float(nav_df["benchmark_value"].iloc[0])
        last_bench = float(nav_df["benchmark_value"].iloc[-1])

        return {
            "client_code": client_code,
            "name": name,
            "inception_date": str(inception),
            "nav_count": len(nav_df),
            "first_date": str(nav_df["nav_date"].iloc[0].date()),
            "last_date": str(nav_df["nav_date"].iloc[-1].date()),
            "first_corpus": first_corpus,
            "last_corpus": last_corpus,
            "first_nav": first_nav,
            "last_nav": last_nav,
            "first_bench": first_bench,
            "last_bench": last_bench,
            "cf_rows": len(cf_rows),
            "metrics_selected": {
                "absolute_return": metrics.get("absolute_return"),
                "absolute_return_simple": metrics.get("absolute_return_simple"),
                "cagr": metrics.get("cagr"),
                "xirr": metrics.get("xirr"),
                "xirr_from_corpus": metrics.get("xirr_from_corpus"),
                "xirr_from_flows": metrics.get("xirr_from_flows"),
                "return_inception": metrics.get("return_inception"),
                "cagr_inception": metrics.get("cagr_inception"),
                "bench_return_inception": metrics.get("bench_return_inception"),
                "bench_cagr_inception": metrics.get("bench_cagr_inception"),
                "bench_return_inception_weighted": metrics.get("bench_return_inception_weighted"),
                "return_5y": metrics.get("return_5y"),
                "return_3y": metrics.get("return_3y"),
                "return_1y": metrics.get("return_1y"),
                "return_6m": metrics.get("return_6m"),
                "bench_return_5y": metrics.get("bench_return_5y"),
                "bench_return_3y": metrics.get("bench_return_3y"),
                "bench_return_1y": metrics.get("bench_return_1y"),
                "bench_return_6m": metrics.get("bench_return_6m"),
            },
        }


async def main():
    codes = ["BJ53", "DP489", "EL53", "EL53MF", "JR98"]
    out = {}
    for code in codes:
        try:
            out[code] = await run_for_client(code)
        except Exception as e:
            out[code] = {"error": str(e)}
    print(json.dumps(out, indent=2, default=str))


asyncio.run(main())
