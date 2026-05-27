"""
Diagnostic for the BJ53 "Absolute Return S&P CNX Nifty [Weighted] %" production gap.

Reference (PMS Portfolio Summary report, 28-Sep-2020 → 25-May-2026):
    Adjusted Return [Weighted] %             = 227.42
    Absolute Return Nifty [Weighted] %       = 74.72   <-- the target
    Average Corpus                           = ₹13,44,632.21

Production was reading ``cpp_risk_metrics.bench_return_inception`` = 70.41% —
4.31pp short of the reference. The unit test on the same function with
inflection-point-only inputs (6 rows) returned 74.46%, well inside the
74.2..75.2 acceptance band. Therefore the divergence is NOT in the function
itself, it is in the inputs the function receives from production.

This script reproduces *both* paths against the live DB and diffs the
intermediates so the gap is visible row-by-row:

  Path A — production: SELECT nav_date, nav_value, invested_amount,
           current_value, benchmark_value, cash_pct, etf_value, cash_value,
           bank_balance FROM cpp_nav_series WHERE client_id=BJ53 AND
           portfolio_id=BJ53's PMS Equity ORDER BY nav_date ASC.
           That is EXACTLY the SELECT in
           ``backend/services/risk_engine.py:445-457``. Feed the resulting
           ``nav_df`` to ``compute_modified_dietz_bench_return``.

  Path B — unit-test: hard-coded inflection-point timeline using the Nifty
           closes the PMS report quotes (11,050.25 → 24,031.70 across 6
           rows). Feed the same function.

The script prints for both paths:
    - V_start, V_end, period_days
    - the derived cash-flow list (date, amount)
    - the benchmark price the function looked up at each CF date (bench_at_cf)
    - the running ``nifty_units`` ledger
    - V_end_bench, denominator, profit_bench, return %

Then it diffs the two ledgers row-by-row. The first row that disagrees IS
the bug — most likely candidates per ``CLAUDE.md`` PR #23/PR #24 hand-off:

    1. terminal ``benchmark_value`` was forward-filled across many days and
       no longer matches the actual Nifty close on the latest nav_date
       (PR #21 callout: 23,643.50 was stuck across 87% of NAV rows before
       the index_prices repoint);
    2. inception ``benchmark_value`` is similarly stale;
    3. cash-flow dates fired ±1 day from the actual settlement date
       because invested_amount changed on the next admin upload, not the
       infusion settlement day, and the as-of bench lookup on that ±1 day
       crossed a holiday;
    4. ``invested_amount[0]`` does not equal the PMS starting corpus
       (₹3.33L) — would happen if a prior NAV row exists for BJ53 with a
       zero corpus before the real inception date.

Run via:
    docker exec client-portal python scripts/diag_bj53_weighted_bench.py
"""

from __future__ import annotations

import asyncio
import os
import sys
from datetime import date
from typing import Any

# Allow `python scripts/diag_bj53_weighted_bench.py` from repo root.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
from sqlalchemy import text

from backend.database import AsyncSessionLocal
from backend.services.modified_dietz import (
    _to_pydate,
    compute_modified_dietz_bench_return,
    extract_modified_dietz_inputs,
)


CLIENT_CODE = "BJ53"


def _trace_bench_ledger(df: pd.DataFrame, label: str) -> dict[str, Any]:
    """Re-run the bench-function logic step-by-step, printing every input.

    Intentionally duplicates the function body so we can SEE the
    intermediates the production function never logs.
    """
    print(f"\n{'─' * 72}")
    print(f"PATH: {label}")
    print(f"{'─' * 72}")
    print(f"nav_df rows: {len(df)}")
    print(f"first row : {df.iloc[0].to_dict()}")
    print(f"last row  : {df.iloc[-1].to_dict()}")

    df = df.sort_values("nav_date").reset_index(drop=True)
    bench_vals = df["benchmark_value"].astype(float)

    inception_bench = float(bench_vals.iloc[0])
    latest_bench = float(bench_vals.iloc[-1])
    print(f"inception_bench (bench_vals[0]) = {inception_bench:.4f}")
    print(f"latest_bench    (bench_vals[-1]) = {latest_bench:.4f}")

    # Stale-tail diagnostic: how many trailing rows share the same bench value?
    tail_constant = 1
    for i in range(len(bench_vals) - 2, -1, -1):
        if float(bench_vals.iloc[i]) == latest_bench:
            tail_constant += 1
        else:
            break
    print(f"trailing rows with bench == latest_bench: {tail_constant}")
    # And how many UNIQUE bench values overall?
    distinct = bench_vals.nunique(dropna=True)
    print(f"distinct benchmark_value entries across the df: {distinct}")

    v_start, v_end, cash_flows, period_days = extract_modified_dietz_inputs(df)
    print(f"v_start     = {v_start:.2f}")
    print(f"v_end       = {v_end:.2f}")
    print(f"period_days = {period_days}")
    print(f"cash_flows  ({len(cash_flows)}):")
    for d, a in cash_flows:
        print(f"   {d}  {a:+,.2f}")

    inception_date = _to_pydate(df["nav_date"].iloc[0])

    bench_lookup = pd.Series(
        bench_vals.values,
        index=pd.to_datetime(df["nav_date"]).values,
    ).sort_index()

    # Initial virtual purchase.
    nifty_units = v_start / inception_bench
    print(f"\nVirtual Nifty purchases:")
    print(f"   {inception_date}  V_start={v_start:>12,.2f}  bench={inception_bench:>10,.4f}  "
          f"units+={v_start / inception_bench:>10,.6f}  total_units={nifty_units:>10,.6f}")

    sum_cf = 0.0
    sum_weighted_cf = 0.0
    for cf_date, amount in cash_flows:
        amt = float(amount)
        ts = pd.Timestamp(cf_date)
        try:
            bench_at_cf = float(bench_lookup.asof(ts))
        except KeyError:
            bench_at_cf = 0.0

        if bench_at_cf is None or pd.isna(bench_at_cf) or bench_at_cf <= 0:
            print(f"   {cf_date}  CF      ={amt:>12,.2f}  bench=  MISSING  "
                  f"units+=     0.000000  total_units={nifty_units:>10,.6f}  [skipped]")
        else:
            units_added = amt / bench_at_cf
            nifty_units += units_added
            print(f"   {cf_date}  CF      ={amt:>12,.2f}  bench={bench_at_cf:>10,.4f}  "
                  f"units+={units_added:>10,.6f}  total_units={nifty_units:>10,.6f}")

        sum_cf += amt
        t_i = max(0, min(period_days, (cf_date - inception_date).days))
        sum_weighted_cf += amt * (period_days - t_i) / period_days

    v_end_bench = nifty_units * latest_bench
    denominator = v_start + sum_weighted_cf
    profit_bench = v_end_bench - v_start - sum_cf
    ret = (profit_bench / denominator) * 100.0 if denominator > 0 else 0.0

    print(f"\nFinal:")
    print(f"   nifty_units     = {nifty_units:>14,.6f}")
    print(f"   latest_bench    = {latest_bench:>14,.4f}")
    print(f"   V_end_bench     = {v_end_bench:>14,.2f}")
    print(f"   sum_cf          = {sum_cf:>14,.2f}")
    print(f"   sum_weighted_cf = {sum_weighted_cf:>14,.2f}")
    print(f"   denominator     = {denominator:>14,.2f}")
    print(f"   profit_bench    = {profit_bench:>14,.2f}")
    print(f"   weighted return = {ret:>14,.4f}%")

    return {
        "label": label,
        "rows": len(df),
        "v_start": v_start,
        "v_end": v_end,
        "period_days": period_days,
        "cash_flows": cash_flows,
        "inception_bench": inception_bench,
        "latest_bench": latest_bench,
        "tail_constant_rows": tail_constant,
        "distinct_bench_values": int(distinct),
        "nifty_units": nifty_units,
        "v_end_bench": v_end_bench,
        "denominator": denominator,
        "profit_bench": profit_bench,
        "weighted_return_pct": ret,
        "library_return_pct": compute_modified_dietz_bench_return(df),
    }


async def _load_production_nav_df(client_code: str) -> pd.DataFrame:
    """Exact replica of the SELECT in risk_engine.run_risk_engine."""
    async with AsyncSessionLocal() as db:
        client_row = await db.execute(
            text("SELECT id FROM cpp_clients WHERE client_code = :code"),
            {"code": client_code},
        )
        cid = client_row.scalar_one_or_none()
        if cid is None:
            raise RuntimeError(f"No client with code {client_code} in cpp_clients")

        pf_row = await db.execute(
            text(
                "SELECT id FROM cpp_portfolios "
                "WHERE client_id = :cid ORDER BY inception_date ASC LIMIT 1"
            ),
            {"cid": cid},
        )
        pid = pf_row.scalar_one_or_none()
        if pid is None:
            raise RuntimeError(f"No portfolio for client {client_code}")

        print(f"Loaded client_id={cid}, portfolio_id={pid} for {client_code}")

        result = await db.execute(
            text("""
                SELECT nav_date, nav_value, invested_amount, current_value,
                       benchmark_value, cash_pct,
                       COALESCE(etf_value, 0) AS etf_value,
                       COALESCE(cash_value, 0) AS cash_value,
                       COALESCE(bank_balance, 0) AS bank_balance
                FROM cpp_nav_series
                WHERE client_id = :cid AND portfolio_id = :pid
                ORDER BY nav_date ASC
            """),
            {"cid": cid, "pid": pid},
        )
        rows = result.fetchall()

    nav_df = pd.DataFrame(rows, columns=[
        "nav_date", "nav_value", "invested_amount", "current_value",
        "benchmark_value", "cash_pct", "etf_value", "cash_value", "bank_balance",
    ])
    nav_df["nav_date"] = pd.to_datetime(nav_df["nav_date"])
    for col in ["nav_value", "invested_amount", "current_value", "benchmark_value",
                 "cash_pct", "etf_value", "cash_value", "bank_balance"]:
        nav_df[col] = pd.to_numeric(nav_df[col], errors="coerce").fillna(0)
    return nav_df.sort_values("nav_date").reset_index(drop=True)


def _build_test_path_nav_df() -> pd.DataFrame:
    """The inputs the PR #23 unit test feeds — return must land 74.46%."""
    nav_dates = [
        date(2020, 9, 28),
        date(2021, 7, 5),
        date(2023, 2, 2),
        date(2023, 2, 21),
        date(2023, 6, 12),
        date(2026, 5, 25),
    ]
    invested = [333_000.0, 533_000.0, 1_033_000.0, 1_890_506.0, 1_990_506.0, 1_990_506.0]
    bench = [11_050.25, 15_722.20, 17_765.00, 17_826.00, 18_601.00, 24_031.70]
    return pd.DataFrame({
        "nav_date": pd.to_datetime(nav_dates),
        "invested_amount": invested,
        "current_value": invested[:-1] + [5_048_414.94],
        "nav_value": invested[:-1] + [5_048_414.94],
        "benchmark_value": bench,
    })


def _diff_results(a: dict, b: dict) -> None:
    print(f"\n{'═' * 72}")
    print("DIFF (production minus test)")
    print(f"{'═' * 72}")
    keys = [
        "rows", "v_start", "v_end", "period_days",
        "inception_bench", "latest_bench",
        "tail_constant_rows", "distinct_bench_values",
        "nifty_units", "v_end_bench", "denominator", "profit_bench",
        "weighted_return_pct", "library_return_pct",
    ]
    for k in keys:
        av, bv = a[k], b[k]
        try:
            diff_str = f"{av - bv:+,.4f}"
        except TypeError:
            diff_str = "(non-numeric)"
        print(f"   {k:<24} prod={av!r}   test={bv!r}   diff={diff_str}")

    prod_dates = {d for d, _ in a["cash_flows"]}
    test_dates = {d for d, _ in b["cash_flows"]}
    only_prod = prod_dates - test_dates
    only_test = test_dates - prod_dates
    if only_prod or only_test:
        print(f"\n   cash-flow date set differs:")
        print(f"     only in production: {sorted(only_prod)}")
        print(f"     only in test:       {sorted(only_test)}")
    else:
        print(f"\n   cash-flow dates match ({len(prod_dates)} flows)")


async def main():
    print(f"BJ53 weighted-benchmark diagnostic — target: 74.72% (PMS reference)\n")

    nav_df_prod = await _load_production_nav_df(CLIENT_CODE)
    nav_df_test = _build_test_path_nav_df()

    result_prod = _trace_bench_ledger(nav_df_prod, "production (cpp_nav_series)")
    result_test = _trace_bench_ledger(nav_df_test, "unit test (PMS HTML)")

    _diff_results(result_prod, result_test)

    print(f"\n{'═' * 72}")
    print("CONCLUSION")
    print(f"{'═' * 72}")
    print(f"Production return: {result_prod['library_return_pct']:.4f}%  (expected ~74.72)")
    print(f"Unit test return : {result_test['library_return_pct']:.4f}%  (expected ~74.72)")


if __name__ == "__main__":
    asyncio.run(main())
