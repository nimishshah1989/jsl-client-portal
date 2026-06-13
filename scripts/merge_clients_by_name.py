"""Unified-login merge runner (PR7a).

Groups per-code clients that are the same person (by exact full name) and folds
each multi-code group onto its survivor — re-parenting portfolios + all per-client
data, soft-retiring non-survivors via ``merged_into``, and writing an audit trail.

SAFE BY DEFAULT: with no flags this is a read-only DRY RUN that prints the plan
and writes nothing. A real run requires ``--execute`` and is transactional with
reconcile-before-commit: it commits ONLY if ``verify_merge_invariants`` passes;
any failure rolls the whole thing back.

Execution order is gated and must NOT be shortcut (see HANDOFF_MULTIPORTFOLIO.md §4):
  1. --dry-run on prod (read-only)            → review the merge report
  2. RDS snapshot
  3. restore → staging → --execute there      → verify green + spot-check a login
  4. prod --execute (recon-before-commit)     → emit credential-delta CSV

Usage:
    python scripts/merge_clients_by_name.py                      # dry run (default)
    python scripts/merge_clients_by_name.py --execute            # real run (prompts)
    python scripts/merge_clients_by_name.py --execute --yes      # real run, no prompt
    python scripts/merge_clients_by_name.py --execute --yes \\
        --expect-aum 905234707.58 --expect-invested 651769759.97 # prod guard rails
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import os
import sys
from decimal import Decimal, InvalidOperation

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select

from backend.database import AsyncSessionLocal
from backend.models.client import Client
from backend.services.merge_service import (
    MergeInvariantError,
    capture_baseline,
    merge_clients_by_name,
    verify_merge_invariants,
)


def _print_report(report: dict, baseline: dict) -> None:
    print("=" * 72)
    print("MERGE PLAN" if report["dry_run"] else "MERGE RESULT")
    print("=" * 72)
    t = report["totals"]
    print(
        f"people={t['people']}  single-code={t['single_code_people']}  "
        f"multi-code groups={t['multi_code_groups']}"
    )
    print(
        f"codes to retire={t['codes_retired']}  "
        f"portfolios re-parented={t['portfolios_reparented']}  "
        f"data rows re-parented={t['rows_reparented']}"
    )
    print("-" * 72)
    for g in report["groups"]:
        s = g["survivor"]
        print(f"• {g['name']!r}")
        print(f"    survivor: id={s['id']} code={s['client_code']} user={s['username']}")
        for r in g["retired"]:
            counts = ", ".join(f"{k}={v}" for k, v in r["reparented"].items() if v)
            print(
                f"    retire  : id={r['id']} code={r['client_code']} user={r['username']} "
                f"portfolios={r['portfolios']} [{counts or 'no data rows'}]"
            )
    print("-" * 72)
    print(f"baseline AUM={baseline['total_aum']}  invested={baseline['total_invested']}  "
          f"portfolios={baseline['portfolio_count']}")


async def _write_credential_csv(db, path: str) -> int:
    """Write the retired-login delta: who needs re-credentialing (usually nobody,
    since retired logins were never used — they alias onto the survivor)."""
    rows = (await db.execute(
        select(
            Client.username, Client.client_code, Client.last_login, Client.merged_into,
        ).where(Client.merged_into.isnot(None))
    )).all()
    id_to_user = dict((await db.execute(select(Client.id, Client.username))).all())
    id_to_code = dict((await db.execute(select(Client.id, Client.client_code))).all())
    with open(path, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow([
            "retired_username", "retired_code", "retired_last_login",
            "survivor_username", "survivor_code", "was_ever_used",
        ])
        for username, code, last_login, survivor_id in rows:
            w.writerow([
                username, code,
                last_login.isoformat() if last_login else "",
                id_to_user.get(survivor_id, ""), id_to_code.get(survivor_id, ""),
                "YES" if last_login else "no",
            ])
    return len(rows)


def _parse_expected(label: str, raw: str | None) -> Decimal | None:
    """Parse an --expect-* guard value to a 2dp Decimal, or exit(2) cleanly.

    Validated up front (before touching the DB) so a typo like Indian-grouped
    digits aborts with a clear message, not an uncaught Decimal traceback.
    """
    if raw is None:
        return None
    try:
        return Decimal(raw).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        print(f"ABORT: --expect-{label} {raw!r} is not a valid number "
              f"(use plain digits, e.g. 905234707.58)", file=sys.stderr)
        raise SystemExit(2)


async def _run(args: argparse.Namespace) -> int:
    expect_aum = _parse_expected("aum", args.expect_aum)
    expect_invested = _parse_expected("invested", args.expect_invested)

    async with AsyncSessionLocal() as db:
        baseline = await capture_baseline(db)

        # Optional prod guard rails: confirm we're pointed at the expected DB/state.
        if expect_aum is not None and baseline["total_aum"] != expect_aum:
            print(f"ABORT: baseline AUM {baseline['total_aum']} != expected {expect_aum}", file=sys.stderr)
            return 2
        if expect_invested is not None and baseline["total_invested"] != expect_invested:
            print(f"ABORT: baseline invested {baseline['total_invested']} != expected {expect_invested}", file=sys.stderr)
            return 2

        if not args.execute:
            report = await merge_clients_by_name(db, dry_run=True)
            await db.rollback()  # belt-and-suspenders; dry run writes nothing
            _print_report(report, baseline)
            print("\nDRY RUN — nothing written. Re-run with --execute to apply.")
            return 0

        # Real run.
        if not args.yes:
            print(
                "About to MERGE per-code clients into survivors (transactional, "
                "recon-before-commit). Ensure an RDS snapshot exists and that a "
                "staging rehearsal passed."
            )
            if input("Type MERGE to proceed: ").strip() != "MERGE":
                print("Aborted (no confirmation).")
                return 1

        try:
            report = await merge_clients_by_name(db, dry_run=False)
            await db.flush()
            verify_report = await verify_merge_invariants(db, baseline)
            await db.commit()
        except MergeInvariantError as exc:
            await db.rollback()
            print(f"\nINVARIANT FAILURE — rolled back, NOTHING committed:\n  {exc}", file=sys.stderr)
            return 3
        except Exception as exc:  # noqa: BLE001 — surface, roll back, fail loudly
            await db.rollback()
            print(f"\nUNEXPECTED ERROR — rolled back, NOTHING committed:\n  {exc}", file=sys.stderr)
            return 4

        # The merge is committed and reconciled. Write the credential delta AFTER
        # commit (it only reads now-persisted merged_into rows), so a filesystem
        # hiccup can never roll back a verified merge.
        _print_report(report, baseline)
        print("\nVERIFY:", json.dumps(verify_report["after"], default=str))
        try:
            n_retired = await _write_credential_csv(db, args.credential_csv)
            print(f"COMMITTED. Credential delta ({n_retired} retired logins) → {args.credential_csv}")
        except OSError as exc:
            print(f"COMMITTED. (credential CSV could not be written: {exc} — "
                  f"re-derive from cpp_merge_audit)", file=sys.stderr)
        return 0


def main() -> None:
    ap = argparse.ArgumentParser(description="Unified-login merge runner (PR7a).")
    ap.add_argument("--execute", action="store_true",
                    help="apply the merge (default is a read-only dry run)")
    ap.add_argument("--yes", action="store_true",
                    help="skip the interactive confirmation prompt (for staging/CI)")
    ap.add_argument("--expect-aum", default=None,
                    help="abort unless baseline total AUM equals this value (prod guard)")
    ap.add_argument("--expect-invested", default=None,
                    help="abort unless baseline total invested equals this value (prod guard)")
    ap.add_argument("--credential-csv", default="merge_credential_delta.csv",
                    help="path for the retired-login delta CSV (real run only)")
    args = ap.parse_args()
    raise SystemExit(asyncio.run(_run(args)))


if __name__ == "__main__":
    main()
