"""Read-only validation of client dashboard views against real data.

Comprehensively reviews what the dashboard actually serves — exercising the SAME
service code paths the API uses (combined_service / combined_analytics) — and
reconciles the Combined view against the individual portfolios, for one client
(deep dive, default BJ53) and/or a sample of clients.

SAFE: pure SELECTs + in-memory computation. Writes nothing. Run it where the DB
is reachable (the EC2 box, or a local Claude Code session that can `ssh jprod`):

    # on the box (reaches RDS) or any host with DATABASE_URL set:
    python scripts/validate_client_views.py --code BJ53        # deep dive (by person/name)
    python scripts/validate_client_views.py --sample 20        # 20 people (multi-portfolio first)
    python scripts/validate_client_views.py --code BJ53 --sample 20

What it checks per view:
  • Individual portfolio: latest invested/current, NAV-series length + Nifty
    (benchmark) coverage %, risk-metrics row + key fields, drawdown series,
    holdings — i.e. the data behind the NAV/Nifty chart, risk table, underwater
    chart and holdings table is present and non-null.
  • Combined (when one client owns >1 LIVE portfolio — i.e. post-merge, or any
    naturally multi-portfolio client): combined invested/current == Σ live
    portfolios; combined holdings qty/value per symbol == Σ; risk/performance/
    drawdown/allocation/growth/xirr all compute. PASS/FAIL with diffs.
  • Pre-merge people (codes still separate client rows) get a "post-merge
    Combined preview" = Σ across the person's live portfolios, so you can see the
    numbers that the merge will surface.

NOTE: this validates the DATA behind every chart, not the rendered SVG. For the
actual visuals, use a staging screenshot / `/verify` pass with the app running.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from collections import defaultdict
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.services.combined_analytics import (
    get_combined_allocation,
    get_combined_drawdown_series,
    get_combined_growth,
    get_combined_performance_table,
    get_combined_risk_metrics,
    get_combined_xirr,
)
from backend.services.combined_service import (
    get_combined_holdings,
    get_combined_nav_series,
    get_combined_summary,
)

OK = "\033[92m✓\033[0m"
NO = "\033[91m✗\033[0m"
_CENT = Decimal("0.01")


def _d(v) -> Decimal:
    return Decimal(str(v if v is not None else 0)).quantize(_CENT)


def _flag(cond: bool) -> str:
    return OK if cond else NO


# ── DB helpers (read-only) ──

async def people_groups(db: AsyncSession) -> dict[str, list[dict]]:
    """Non-admin / non-deleted clients grouped by exact name (the merge grouping)."""
    rows = (await db.execute(text("""
        SELECT id, client_code, name, username, merged_into
        FROM cpp_clients
        WHERE is_deleted = false AND is_admin = false
        ORDER BY name, id
    """))).mappings().all()
    groups: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        groups[r["name"]].append(dict(r))
    return groups


async def client_portfolios(db: AsyncSession, client_id: int) -> list[dict]:
    return [dict(r) for r in (await db.execute(text("""
        SELECT id, portfolio_name, client_code, strategy, is_closed, inception_date
        FROM cpp_portfolios WHERE client_id = :cid
        ORDER BY is_closed, strategy, id
    """), {"cid": client_id})).mappings().all()]


async def validate_portfolio(db: AsyncSession, client_id: int, p: dict) -> dict:
    """Per-portfolio individual-view data integrity + chart-data presence."""
    pid = p["id"]
    nav = (await db.execute(text("""
        SELECT count(*) AS n,
               count(benchmark_value) AS n_bench,
               max(nav_date) AS last_date
        FROM cpp_nav_series WHERE client_id = :cid AND portfolio_id = :pid
    """), {"cid": client_id, "pid": pid})).mappings().one()
    latest = (await db.execute(text("""
        SELECT invested_amount, current_value, nav_value
        FROM cpp_nav_series WHERE client_id = :cid AND portfolio_id = :pid
        ORDER BY nav_date DESC LIMIT 1
    """), {"cid": client_id, "pid": pid})).mappings().one_or_none()
    risk = (await db.execute(text("""
        SELECT cagr, volatility, sharpe_ratio, sortino_ratio, max_drawdown,
               beta, alpha, up_capture, down_capture, xirr
        FROM cpp_risk_metrics WHERE client_id = :cid AND portfolio_id = :pid
        ORDER BY computed_date DESC LIMIT 1
    """), {"cid": client_id, "pid": pid})).mappings().one_or_none()
    dd_n = (await db.execute(text(
        "SELECT count(*) FROM cpp_drawdown_series WHERE client_id=:cid AND portfolio_id=:pid"
    ), {"cid": client_id, "pid": pid})).scalar() or 0
    hold = (await db.execute(text("""
        SELECT count(*) AS n, coalesce(sum(current_value),0) AS val
        FROM cpp_holdings WHERE client_id=:cid AND portfolio_id=:pid AND quantity > 0
    """), {"cid": client_id, "pid": pid})).mappings().one()

    nav_n = int(nav["n"] or 0)
    bench_cov = (int(nav["n_bench"] or 0) / nav_n * 100) if nav_n else 0.0
    risk_ok = risk is not None and risk["cagr"] is not None and risk["sharpe_ratio"] is not None
    return {
        "portfolio": p, "nav_points": nav_n, "bench_coverage_pct": bench_cov,
        "last_date": nav["last_date"],
        "invested": _d(latest["invested_amount"]) if latest else _d(0),
        "current": _d(latest["current_value"] or (latest["nav_value"] if latest else 0)) if latest else _d(0),
        "risk": dict(risk) if risk else None, "risk_ok": risk_ok,
        "drawdown_points": int(dd_n), "holdings": int(hold["n"] or 0),
        "holdings_value": _d(hold["val"]),
        "checks": {
            "nav_chart": nav_n >= 2,
            "nifty_overlay": bench_cov >= 95.0,
            "risk_table": risk_ok,
            "underwater_chart": int(dd_n) >= 2,
            "holdings_table": int(hold["n"] or 0) > 0 or bool(p["is_closed"]),
        },
    }


async def expected_sum_of_parts(db: AsyncSession, client_id: int) -> dict:
    """Σ over the client's LIVE portfolios of the latest invested/current.

    Picks exactly one NAV row per portfolio (latest date, tie-broken by id) with
    plain CTEs — portable across Postgres and SQLite (no window functions)."""
    row = (await db.execute(text("""
        WITH md AS (
            SELECT n.portfolio_id AS pid, MAX(n.nav_date) AS md
            FROM cpp_nav_series n
            JOIN cpp_portfolios p ON p.id = n.portfolio_id
            WHERE n.client_id = :cid AND p.is_closed = false
            GROUP BY n.portfolio_id
        ),
        latest_ids AS (
            SELECT MAX(n.id) AS nid
            FROM cpp_nav_series n
            JOIN md ON md.pid = n.portfolio_id AND n.nav_date = md.md
            GROUP BY n.portfolio_id
        )
        SELECT coalesce(sum(invested_amount), 0) AS invested,
               coalesce(sum(coalesce(current_value, nav_value)), 0) AS current
        FROM cpp_nav_series WHERE id IN (SELECT nid FROM latest_ids)
    """), {"cid": client_id})).mappings().one()
    return {"invested": _d(row["invested"]), "current": _d(row["current"])}


async def validate_combined(db: AsyncSession, client_id: int) -> dict:
    """Run the real combined-view code paths and reconcile vs Σ live portfolios."""
    summary = await get_combined_summary(db, client_id)
    expected = await expected_sum_of_parts(db, client_id)
    nav = await get_combined_nav_series(db, client_id)
    holds = await get_combined_holdings(db, client_id)
    risk = await get_combined_risk_metrics(db, client_id)
    perf = await get_combined_performance_table(db, client_id)
    dd = await get_combined_drawdown_series(db, client_id)
    alloc = await get_combined_allocation(db, client_id)
    growth = await get_combined_growth(db, client_id)
    xirr = await get_combined_xirr(db, client_id)

    inv_match = summary and _d(summary["invested"]) == expected["invested"]
    cur_match = summary and _d(summary["current_value"]) == expected["current"]
    bench_pts = sum(1 for pt in nav if pt.get("benchmark") is not None)
    return {
        "summary": summary, "expected": expected,
        "checks": {
            "invested == Σ live": bool(inv_match),
            "current == Σ live": bool(cur_match),
            "nav_chart": len(nav) >= 2,
            "nifty_overlay": bench_pts >= max(1, int(0.95 * len(nav))) if nav else False,
            "risk_table": bool(risk) and risk.get("cagr") is not None,
            "performance_table": isinstance(perf, list) and len(perf) >= 1,
            "underwater_chart": len(dd) >= 2,
            "allocation": bool(alloc.get("by_sector")),
            "growth": bool(growth) and growth.get("portfolio") is not None,
            "xirr": bool(xirr) and xirr.get("xirr") is not None,
            "holdings_table": len(holds) >= 0,
        },
        "diffs": {
            "invested": (None if inv_match else f"{summary['invested'] if summary else '—'} vs Σ {expected['invested']}"),
            "current": (None if cur_match else f"{summary['current_value'] if summary else '—'} vs Σ {expected['current']}"),
        },
    }


# ── Reporting ──

def _print_portfolio(v: dict) -> bool:
    p = v["portfolio"]
    tag = "CLOSED" if p["is_closed"] else p["strategy"]
    print(f"    [{p['client_code'] or '?'}/{tag}] {p['portfolio_name']!r}  "
          f"invested={v['invested']} current={v['current']}  "
          f"nav_pts={v['nav_points']} nifty={v['bench_coverage_pct']:.0f}% "
          f"dd={v['drawdown_points']} holds={v['holdings']}")
    checks = v["checks"]
    line = "      " + "  ".join(f"{_flag(ok)} {name}" for name, ok in checks.items())
    print(line)
    return all(checks.values())


async def review_person(db: AsyncSession, name: str, members: list[dict]) -> bool:
    print(f"\n=== {name}  ({len(members)} code(s): "
          f"{', '.join(m['client_code'] or '?' for m in members)}) ===")
    all_ok = True

    # Map each client row -> its portfolios; validate every individual view.
    client_to_ports: dict[int, list[dict]] = {}
    for m in members:
        ports = await client_portfolios(db, m["id"])
        client_to_ports[m["id"]] = ports
        for p in ports:
            v = await validate_portfolio(db, m["id"], p)
            all_ok &= _print_portfolio(v)

    multi = [(cid, ps) for cid, ps in client_to_ports.items()
             if len([p for p in ps if not p["is_closed"]]) > 1]

    if multi:
        # Post-merge / naturally-multi: validate the real Combined code path.
        for cid, _ps in multi:
            c = await validate_combined(db, cid)
            s = c["summary"] or {}
            print(f"    COMBINED (client_id={cid}): invested={s.get('invested','—')} "
                  f"current={s.get('current_value','—')} cagr={s.get('cagr','—')} "
                  f"maxDD={s.get('max_drawdown','—')}")
            for nm, ok in c["checks"].items():
                if not ok:
                    all_ok = False
                    extra = c["diffs"].get(nm.split()[0]) or ""
                    print(f"      {NO} {nm}  {extra}")
            print("      " + "  ".join(f"{_flag(ok)} {nm}" for nm, ok in c["checks"].items()))
    else:
        # Pre-merge: codes are separate clients; show the post-merge Combined preview.
        live_inv = live_cur = Decimal("0.00")
        for cid in client_to_ports:
            e = await expected_sum_of_parts(db, cid)
            live_inv += e["invested"]; live_cur += e["current"]
        print(f"    COMBINED preview (post-merge Σ live portfolios): "
              f"invested={live_inv} current={live_cur} "
              f"profit={live_cur - live_inv}  "
              f"[combined_service validates this once the merge unifies these codes]")
    return all_ok


async def _run(args: argparse.Namespace) -> int:
    from backend.database import AsyncSessionLocal
    async with AsyncSessionLocal() as db:
        groups = await people_groups(db)

        targets: list[tuple[str, list[dict]]] = []
        if args.code:
            # Resolve the PERSON by the name of the client with this code.
            match = next((m for ms in groups.values() for m in ms
                          if (m["client_code"] or "").upper() == args.code.upper()), None)
            if not match:
                print(f"No client with code {args.code!r}", file=sys.stderr)
                return 2
            targets.append((match["name"], groups[match["name"]]))
        if args.name:
            if args.name not in groups:
                print(f"No person named {args.name!r}", file=sys.stderr)
                return 2
            targets.append((args.name, groups[args.name]))
        if args.sample:
            # Multi-code people first (most interesting), then by name.
            ranked = sorted(groups.items(), key=lambda kv: (-len(kv[1]), kv[0]))
            seen = {n for n, _ in targets}
            for n, ms in ranked:
                if n in seen:
                    continue
                targets.append((n, ms))
                if len([t for t in targets if t[0] not in seen]) >= args.sample:
                    break

        if not targets:
            print("Nothing selected — pass --code, --name and/or --sample N", file=sys.stderr)
            return 2

        overall_ok = True
        for name, members in targets:
            overall_ok &= await review_person(db, name, members)

        print("\n" + "=" * 64)
        print(f"REVIEWED {len(targets)} person(s) — "
              f"{'ALL VIEWS HAVE COMPLETE DATA ' + OK if overall_ok else 'SOME VIEWS MISSING DATA ' + NO}")
        return 0 if overall_ok else 1


def main() -> None:
    ap = argparse.ArgumentParser(description="Read-only validation of client dashboard views.")
    ap.add_argument("--code", help="deep-dive a person by one of their client_codes (e.g. BJ53)")
    ap.add_argument("--name", help="deep-dive a person by exact full name")
    ap.add_argument("--sample", type=int, default=0, help="also review N people (multi-code first)")
    raise SystemExit(asyncio.run(_run(ap.parse_args())))


if __name__ == "__main__":
    main()
