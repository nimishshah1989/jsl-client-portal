"""Flag dormant / empty portfolios as closed (is_closed = true).

The consolidated PMS NAV file only reports *active* accounts, so a live
(is_closed=false) portfolio whose NAV stopped long ago — or that has no NAV at
all (an empty stub like JA59) — is almost certainly redeemed/closed but was never
flagged (its code lacks a CLOSE/CLO suffix). Such accounts inflate firm AUM at a
stale value and clutter live/Combined views.

This flags them ``is_closed = true`` — data is RETAINED (closed accounts are kept,
just excluded from live aggregates and Combined). Fully reversible (set back to
false). SAFE BY DEFAULT: a dry run that lists exactly what it would flag and
writes nothing. A real run is transactional and reports the live-AUM delta.

Run dry-run on staging → review → --execute on staging → re-validate → prod.

    python scripts/flag_dormant_portfolios.py                 # dry run, 90-day default
    python scripts/flag_dormant_portfolios.py --days 90       # tune the staleness window
    python scripts/flag_dormant_portfolios.py --no-empty      # skip no-NAV stubs
    python scripts/flag_dormant_portfolios.py --execute --yes
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.services.strategy_filter import active_cutoff


async def find_dormant_portfolios(
    db: AsyncSession, days: int = 90, include_empty: bool = True,
) -> list[dict]:
    """Live, non-admin, non-deleted portfolios whose latest NAV is older than
    ``days`` before the firm's most recent NAV date, plus (optionally) live
    portfolios with no NAV at all. Returns audit rows; writes nothing."""
    cutoff = await active_cutoff(db, window_days=days)

    conds = []
    params: dict = {}
    if cutoff is not None:
        conds.append("lpf.last_nav < :cutoff")
        params["cutoff"] = cutoff
    if include_empty:
        conds.append("lpf.last_nav IS NULL")
    if not conds:
        return []
    where_dormant = " OR ".join(conds)

    rows = (await db.execute(text(f"""
        WITH lpf AS (
            SELECT portfolio_id, MAX(nav_date) AS last_nav
            FROM cpp_nav_series GROUP BY portfolio_id
        ),
        latest_val AS (
            SELECT n.portfolio_id, n.current_value, n.nav_value,
                   ROW_NUMBER() OVER (PARTITION BY n.portfolio_id
                                      ORDER BY n.nav_date DESC, n.id DESC) AS rn
            FROM cpp_nav_series n
        )
        SELECT p.id, p.client_code, p.strategy, c.name, c.id AS client_id,
               lpf.last_nav,
               COALESCE(lv.current_value, lv.nav_value, 0) AS last_value
        FROM cpp_portfolios p
        JOIN cpp_clients c ON c.id = p.client_id
        LEFT JOIN lpf ON lpf.portfolio_id = p.id
        LEFT JOIN latest_val lv ON lv.portfolio_id = p.id AND lv.rn = 1
        WHERE p.is_closed = false AND c.is_admin = false AND c.is_deleted = false
          AND ({where_dormant})
        ORDER BY lpf.last_nav NULLS FIRST
    """), params)).mappings().all()
    return [dict(r) for r in rows]


async def _live_aum(db: AsyncSession) -> float:
    """Σ latest nav_value of LIVE (is_closed=false) portfolios — the live AUM."""
    val = (await db.execute(text("""
        WITH md AS (
            SELECT n.portfolio_id AS pid, MAX(n.nav_date) AS md
            FROM cpp_nav_series n JOIN cpp_portfolios p ON p.id = n.portfolio_id
            WHERE p.is_closed = false
            GROUP BY n.portfolio_id
        ),
        latest_ids AS (
            SELECT MAX(n2.id) AS nid FROM cpp_nav_series n2
            JOIN md ON md.pid = n2.portfolio_id AND n2.nav_date = md.md
            GROUP BY n2.portfolio_id
        )
        SELECT COALESCE(SUM(nav_value), 0) FROM cpp_nav_series
        WHERE id IN (SELECT nid FROM latest_ids)
    """))).scalar()
    return float(val or 0)


async def _run(args: argparse.Namespace) -> int:
    from backend.database import AsyncSessionLocal
    async with AsyncSessionLocal() as db:
        dormant = await find_dormant_portfolios(db, days=args.days, include_empty=not args.no_empty)
        live_before = await _live_aum(db)

        print("=" * 78)
        print(f"DORMANT PORTFOLIOS (live, no NAV in > {args.days} days"
              f"{'' if args.no_empty else ' OR no NAV at all'}) — {len(dormant)} found")
        print("=" * 78)
        for r in dormant:
            last = r["last_nav"] or "NEVER"
            print(f"  pf={r['id']:<5} code={ (r['client_code'] or '?'):<12} "
                  f"last_nav={str(last):<12} value=₹{float(r['last_value']):,.0f}  {r['name']}")
        print("-" * 78)
        print(f"live AUM now: ₹{live_before:,.0f}   (would drop by the values above)")

        if not args.execute:
            print("\nDRY RUN — nothing written. Re-run with --execute to flag these is_closed=true.")
            return 0
        if not dormant:
            print("\nNothing to flag.")
            return 0

        if not args.yes:
            if input(f"\nFlag {len(dormant)} portfolios is_closed=true? Type YES: ").strip() != "YES":
                print("Aborted.")
                return 1

        ids = [r["id"] for r in dormant]
        try:
            await db.execute(
                text("UPDATE cpp_portfolios SET is_closed = true WHERE id IN :ids")
                .bindparams(bindparam("ids", expanding=True)),
                {"ids": ids},
            )
            await db.flush()
            live_after = await _live_aum(db)
            await db.commit()
        except Exception as exc:  # noqa: BLE001 — surface + roll back
            await db.rollback()
            print(f"\nERROR — rolled back, nothing changed:\n  {exc}", file=sys.stderr)
            return 2

        print(f"\nFLAGGED {len(ids)} portfolios is_closed=true.")
        print(f"live AUM: ₹{live_before:,.0f} → ₹{live_after:,.0f} "
              f"(−₹{live_before - live_after:,.0f})")
        return 0


def main() -> None:
    ap = argparse.ArgumentParser(description="Flag dormant/empty portfolios as closed.")
    ap.add_argument("--days", type=int, default=90,
                    help="staleness threshold in days (default 90)")
    ap.add_argument("--no-empty", action="store_true",
                    help="do NOT flag live portfolios that have no NAV at all")
    ap.add_argument("--execute", action="store_true", help="apply (default is a dry run)")
    ap.add_argument("--yes", action="store_true", help="skip the confirmation prompt")
    raise SystemExit(asyncio.run(_run(ap.parse_args())))


if __name__ == "__main__":
    main()
