"""Backfill cpp_portfolios.client_code / strategy / is_closed.

Sets each portfolio's source UCC and derives its strategy + closed flag from the
owning client's code. The rule lives in backend/services/classification.py (the
single source of truth shared with ongoing ingestion), so this never drifts.

Idempotent and safe to re-run: it only TAGS portfolios (no destructive change)
and recomputes every value each run. Run on a host that can reach RDS (the EC2
box), after applying scripts/migrate_add_portfolio_strategy.sql.

Usage:
    python scripts/backfill_portfolio_strategy.py             # apply
    python scripts/backfill_portfolio_strategy.py --dry-run   # report only
"""

import argparse
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

import psycopg2

from backend.services.classification import classify_code


def _dsn() -> str:
    url = os.getenv("DATABASE_URL_SYNC") or os.getenv("DATABASE_URL", "")
    if not url:
        raise SystemExit("DATABASE_URL_SYNC / DATABASE_URL not set")
    return url.replace("postgresql+asyncpg://", "postgresql://")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="report tally, write nothing")
    args = ap.parse_args()

    conn = psycopg2.connect(_dsn())
    conn.autocommit = False
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT p.id, c.client_code
                FROM cpp_portfolios p
                JOIN cpp_clients c ON c.id = p.client_id
                """
            )
            rows = cur.fetchall()

            strat_tally: Counter = Counter()
            closed = 0
            updates = []
            for pid, code in rows:
                result = classify_code(code)
                strat_tally[result.strategy] += 1
                if result.is_closed:
                    closed += 1
                updates.append((code, result.strategy, result.is_closed, pid))

            if not args.dry_run and updates:
                cur.executemany(
                    """
                    UPDATE cpp_portfolios
                    SET client_code = %s, strategy = %s, is_closed = %s
                    WHERE id = %s
                    """,
                    updates,
                )
                conn.commit()

        print(f"Portfolios processed: {len(rows)}")
        for strat, n in sorted(strat_tally.items()):
            print(f"  {strat:<8} {n}")
        print(f"  CLOSED   {closed}")
        print("DRY RUN - no changes written." if args.dry_run else "Applied.")
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()
