"""Read-only validation of the admin aggregate firm metrics.

Cross-checks the TWO CAGR/risk methods that feed the admin dashboard so we can
see, on real data, exactly where they diverge:

  A. Composite TWR  — aggregate_service.get_aggregate_risk_metrics (the Strategy
     Summary table + Aggregate Performance/Risk Scorecard). Time-weighted.
  B. Card "Blended" — admin_analytics.compute_dashboard_analytics: AUM-weighted
     average of each portfolio's OWN stored since-inception CAGR.

For COMBINED + each bucket it prints AUM, method-A CAGR/MaxDD/Sharpe, method-B
CAGR/MaxDD/Sharpe, and the AUM-weighted blend of the bucket composites. It also
dumps the top portfolios by AUM with their stored CAGR + inception + nav-point
count, so a low blended number can be explained (big young/flat sleeves).

SAFE: pure reads, no writes. Run from the prod image container:

    docker run --rm --network host --env-file "$PWD/.env" \
      -v "$PWD/scripts:/app/scripts" client-portal \
      python /app/scripts/validate_admin_aggregates.py
"""

from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text

from backend.database import AsyncSessionLocal
from backend.services.admin_analytics import compute_dashboard_analytics
from backend.services.aggregate_service import (
    _fetch_bucket_aum,
    get_aggregate_risk_metrics,
)
from backend.services.strategy_filter import active_cutoff

BUCKETS = ["COMBINED", "LEADERS", "PASSIVE", "IND11"]


def _f(v) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


async def main() -> None:
    async with AsyncSessionLocal() as db:
        cutoff = await active_cutoff(db)

        rows = {}
        print("=" * 92)
        print("ADMIN AGGREGATE VALIDATION  (active-only)  — composite (A) vs card-blended (B)")
        print("=" * 92)
        print(f"{'bucket':9} {'AUM(Cr)':>9} {'A:cagr':>9} {'B:cagr':>9} "
              f"{'A:maxDD':>9} {'B:maxDD':>9} {'A:sharpe':>9} {'B:sharpe':>9}")
        for strat in BUCKETS:
            comp = await get_aggregate_risk_metrics(db, strat, include_inactive=False)   # A
            card = await compute_dashboard_analytics(db, strat, include_inactive=False)   # B
            aum = await _fetch_bucket_aum(db, strat, include_inactive=False, cutoff=cutoff)
            rows[strat] = {
                "aum": aum,
                "a_cagr": _f(comp["cagr"]),
                "b_cagr": _f(card["blended_cagr"]),
                "a_dd": _f(comp["max_drawdown"]),
                "b_dd": _f(card["avg_max_drawdown"]),
                "a_sharpe": _f(comp["sharpe_ratio"]),
                "b_sharpe": _f(card["blended_sharpe"]),
            }
            r = rows[strat]
            print(f"{strat:9} {aum/1e7:>9.2f} {r['a_cagr']:>9.2f} {r['b_cagr']:>9.2f} "
                  f"{r['a_dd']:>9.2f} {r['b_dd']:>9.2f} {r['a_sharpe']:>9.2f} {r['b_sharpe']:>9.2f}")

        # ── Reconciliation checks ────────────────────────────────────────────
        print("-" * 92)
        leaf = ["LEADERS", "PASSIVE", "IND11"]
        sum_leaf_aum = sum(rows[s]["aum"] for s in leaf)
        comb_aum = rows["COMBINED"]["aum"]
        print(f"AUM reconciliation:  Σ(leaf buckets) = ₹{sum_leaf_aum/1e7:.2f} Cr   "
              f"vs COMBINED = ₹{comb_aum/1e7:.2f} Cr   "
              f"(Δ ₹{(comb_aum - sum_leaf_aum)/1e7:.2f} Cr)")

        if comb_aum > 0:
            blend_of_composites = sum(rows[s]["aum"] * rows[s]["a_cagr"] for s in leaf) / comb_aum
            print(f"AUM-weighted blend of BUCKET composites (A) = {blend_of_composites:.2f}%  "
                  f"→ this is what the Combined headline SHOULD be near")
            print(f"COMBINED composite CAGR (A)                  = {rows['COMBINED']['a_cagr']:.2f}%")
            print(f"COMBINED card blended CAGR (B)               = {rows['COMBINED']['b_cagr']:.2f}%  "
                  f"← the suspect number")

        # ── Sanity bounds: anything here is a red flag ───────────────────────
        print("-" * 92)
        flags = []
        for strat, r in rows.items():
            if not (-50 <= r["a_cagr"] <= 100):
                flags.append(f"{strat}: composite CAGR {r['a_cagr']}% out of sane range")
            if r["a_dd"] < -99:
                flags.append(f"{strat}: composite MaxDD {r['a_dd']}% (≈ total wipeout — suspect)")
            if abs(r["a_cagr"] - r["b_cagr"]) > 5:
                flags.append(f"{strat}: CAGR methods disagree by "
                             f"{abs(r['a_cagr'] - r['b_cagr']):.1f}pts (A={r['a_cagr']} B={r['b_cagr']})")
        print("FLAGS:" if flags else "No sanity-bound flags.")
        for f in flags:
            print(f"  ⚠ {f}")

        # ── Why is the blend low? Top portfolios by AUM with their stored CAGR ─
        print("-" * 92)
        print("TOP 15 LIVE PORTFOLIOS BY AUM (their OWN stored since-inception CAGR):")
        active = "" if cutoff is None else (
            " AND p.id IN (SELECT portfolio_id FROM cpp_nav_series "
            "GROUP BY portfolio_id HAVING MAX(nav_date) >= :cut)")
        res = await db.execute(text(f"""
            WITH latest_nav AS (
                SELECT n.portfolio_id AS pid, n.nav_value AS aum, n.nav_date AS d,
                       ROW_NUMBER() OVER (PARTITION BY n.portfolio_id
                                          ORDER BY n.nav_date DESC, n.id DESC) AS rn
                FROM cpp_nav_series n
            ),
            latest_risk AS (
                SELECT r.portfolio_id AS pid, r.cagr AS cagr,
                       ROW_NUMBER() OVER (PARTITION BY r.portfolio_id
                                          ORDER BY r.computed_date DESC, r.id DESC) AS rn
                FROM cpp_risk_metrics r
            ),
            np AS (
                SELECT portfolio_id AS pid, COUNT(*) AS pts FROM cpp_nav_series GROUP BY portfolio_id
            )
            SELECT p.client_code, ln.aum, lr.cagr, p.inception_date, np.pts, p.strategy
            FROM cpp_portfolios p
            JOIN latest_nav ln ON ln.pid = p.id AND ln.rn = 1
            LEFT JOIN latest_risk lr ON lr.pid = p.id AND lr.rn = 1
            LEFT JOIN np ON np.pid = p.id
            WHERE p.is_closed = false {active}
            ORDER BY ln.aum DESC
            LIMIT 15
        """), {"cut": cutoff} if cutoff is not None else {})
        print(f"  {'code':12} {'AUM(Cr)':>9} {'cagr%':>8} {'incept':>12} {'navpts':>7} strategy")
        for row in res.fetchall():
            print(f"  {str(row.client_code or ''):12} {_f(row.aum)/1e7:>9.2f} "
                  f"{_f(row.cagr):>8.2f} {str(row.inception_date or ''):>12} "
                  f"{int(row.pts or 0):>7} {row.strategy}")
        print("=" * 92)


if __name__ == "__main__":
    asyncio.run(main())
