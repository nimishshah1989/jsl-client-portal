"""Read-only reconciliation sweep over ALL client holdings.

Answers "do the holdings weights sum to 100%?" for every live portfolio, firm-
wide — and explains where they don't. For each portfolio it compares the
official NAV against what the Current Holdings table can actually itemise:

    residual = nav_value
             - Σ(equity holdings at live price, excl. cash instruments)
             - cash_value - bank_balance - etf_value      (the NAV cash breakdown)

A non-zero residual is the % the holdings table fails to account for (so the
weights stop at < 100% on the dashboard). Mirrors backend/routers/portfolio.py
get_holdings exactly (same cash-instrument rule, same Liquidity% fallback).

Prints firm totals, how many portfolios miss the 100% mark, the worst offenders,
and a likely-cause tag per row so the fix targets the real problem (missing
positions vs stale prices vs cash understatement).

SAFE: pure reads. Run from the prod image container:

    docker run --rm --network host --env-file "$PWD/.env" \
      -v "$PWD/scripts:/app/scripts" client-portal \
      python /app/scripts/reconcile_holdings.py
"""

from __future__ import annotations

import asyncio
import os
import sys
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text

from backend.database import AsyncSessionLocal
from backend.routers.portfolio import _is_cash_instrument  # exact prod rule

TOL_PCT = Decimal("1.0")   # flag a portfolio if |residual| exceeds this % of NAV
D0 = Decimal("0")


def _cause(equity_live: Decimal, residual: Decimal, nav: Decimal) -> str:
    """Best-guess label for a non-reconciling portfolio."""
    if abs(residual) <= nav * TOL_PCT / 100:
        return "ok"
    if equity_live == D0 and residual > D0:
        return "NO HOLDINGS INGESTED (equity in NAV, none itemised)"
    if residual > D0:
        return "UNDER-ITEMISED (stale live price or missing positions)"
    return "OVER-ITEMISED (holdings priced above NAV equity / cash understated)"


async def main() -> None:
    async with AsyncSessionLocal() as db:
        # Per-portfolio latest NAV row (portable: MAX(id) at MAX(nav_date)).
        nav_rows = (await db.execute(text("""
            WITH md AS (
                SELECT portfolio_id, MAX(nav_date) AS mxd
                FROM cpp_nav_series GROUP BY portfolio_id
            ),
            latest_ids AS (
                SELECT MAX(n.id) AS nid FROM cpp_nav_series n
                JOIN md ON md.portfolio_id = n.portfolio_id AND n.nav_date = md.mxd
                GROUP BY n.portfolio_id
            )
            SELECT n.portfolio_id AS pid, p.client_code AS code, p.strategy AS strat,
                   n.nav_value AS nav,
                   COALESCE(n.cash_value, 0) AS cash_value,
                   COALESCE(n.bank_balance, 0) AS bank,
                   COALESCE(n.etf_value, 0) AS etf,
                   COALESCE(n.cash_pct, 0) AS cash_pct
            FROM cpp_nav_series n
            JOIN cpp_portfolios p ON p.id = n.portfolio_id
            WHERE n.id IN (SELECT nid FROM latest_ids) AND p.is_closed = false
        """))).fetchall()

        # Equity-at-live-price per portfolio (exclude cash instruments, prod rule).
        hold_rows = (await db.execute(text("""
            SELECT portfolio_id AS pid, symbol, asset_class AS ac,
                   COALESCE(current_value, 0) AS cv
            FROM cpp_holdings
        """))).fetchall()
        equity_by_pid: dict[int, Decimal] = {}
        for h in hold_rows:
            if _is_cash_instrument(h.symbol, h.ac):
                continue
            equity_by_pid[h.pid] = equity_by_pid.get(h.pid, D0) + Decimal(str(h.cv))

        results = []
        for r in nav_rows:
            nav = Decimal(str(r.nav))
            if nav <= D0:
                continue
            equity_live = equity_by_pid.get(r.pid, D0)
            cash = Decimal(str(r.cash_value)) + Decimal(str(r.bank)) + Decimal(str(r.etf))
            # Same Liquidity% fallback as get_holdings when the breakdown is absent.
            if cash == D0 and Decimal(str(r.cash_pct)) > D0:
                cash = nav * Decimal(str(r.cash_pct)) / 100
            residual = nav - equity_live - cash
            results.append({
                "code": r.code, "strat": r.strat, "nav": nav,
                "equity": equity_live, "cash": cash, "residual": residual,
                "pct": (residual / nav * 100),
            })

        # ── Firm rollup ──────────────────────────────────────────────────────
        n = len(results)
        sum_nav = sum(x["nav"] for x in results)
        sum_eq = sum(x["equity"] for x in results)
        sum_cash = sum(x["cash"] for x in results)
        sum_res = sum(x["residual"] for x in results)
        bad = [x for x in results if abs(x["pct"]) > TOL_PCT]
        big = [x for x in results if abs(x["pct"]) > 10]
        noing = [x for x in results if x["equity"] == D0 and x["residual"] > D0]

        def cr(v):  # ₹ in crore
            return f"{float(v)/1e7:,.2f}"

        print("=" * 96)
        print(f"HOLDINGS RECONCILIATION — {n} live portfolios   (tolerance ±{TOL_PCT}% of NAV)")
        print("=" * 96)
        print(f"Σ NAV          ₹{cr(sum_nav)} Cr")
        print(f"Σ equity(live) ₹{cr(sum_eq)} Cr   Σ cash ₹{cr(sum_cash)} Cr   "
              f"Σ residual ₹{cr(sum_res)} Cr  ({float(sum_res/sum_nav*100):.2f}% of NAV)")
        print(f"portfolios off by >±{TOL_PCT}%: {len(bad)}/{n}   "
              f"off by >±10%: {len(big)}   with NO holdings ingested: {len(noing)}")
        print("-" * 96)
        print(f"{'code':12} {'strat':8} {'NAV(Cr)':>9} {'equity':>9} {'cash':>9} "
              f"{'resid':>9} {'resid%':>8}  cause")
        for x in sorted(bad, key=lambda y: abs(y["pct"]), reverse=True)[:30]:
            print(f"{str(x['code'] or ''):12} {str(x['strat'] or ''):8} "
                  f"{cr(x['nav']):>9} {cr(x['equity']):>9} {cr(x['cash']):>9} "
                  f"{cr(x['residual']):>9} {float(x['pct']):>7.1f}%  "
                  f"{_cause(x['equity'], x['residual'], x['nav'])}")
        print("=" * 96)
        print("Interpretation: residual% is the slice the Current Holdings table can't")
        print("itemise — i.e. how far its weights fall short of 100%. Fix targets the")
        print("dominant cause above; the table will also get a reconciling line so it")
        print("always closes to 100%.")


if __name__ == "__main__":
    asyncio.run(main())
