"""
Direct data ingestion script — run on server after deploying.

Usage:
    python scripts/ingest_data.py --nav data/nav_report.xlsx
    python scripts/ingest_data.py --txn data/transactions.xlsx
    python scripts/ingest_data.py --nav data/nav.xlsx --txn data/txn.xlsx

Parses the PMS backoffice files, upserts into the database,
fetches benchmark data, and computes risk metrics.
"""

import argparse
import asyncio
import logging
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.services.nav_parser import parse_nav_file
from backend.services.txn_parser import parse_transaction_file

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)
logger = logging.getLogger("ingest")


def test_parse_nav(filepath: str) -> None:
    """Parse NAV file and print summary (no DB required)."""
    logger.info("Parsing NAV file: %s", filepath)
    records = parse_nav_file(filepath)
    if not records:
        logger.error("No records parsed from NAV file!")
        return

    # Summarize
    clients = set(r["client_code"] for r in records)
    logger.info("Parsed %d NAV records for %d clients", len(records), len(clients))

    # Show first client's data
    first_client = records[0]["client_code"]
    client_records = [r for r in records if r["client_code"] == first_client]
    logger.info(
        "Sample — Client %s (%s): %d records, date range %s to %s",
        first_client,
        records[0]["client_name"],
        len(client_records),
        client_records[0]["date"].strftime("%Y-%m-%d"),
        client_records[-1]["date"].strftime("%Y-%m-%d"),
    )
    logger.info(
        "  First NAV: %s, Last NAV: %s, First Corpus: %s, Last Corpus: %s",
        client_records[0]["nav"],
        client_records[-1]["nav"],
        client_records[0]["corpus"],
        client_records[-1]["corpus"],
    )

    # Show all client codes
    logger.info("All clients: %s", sorted(clients))


def test_parse_txn(filepath: str) -> None:
    """Parse Transaction file and print summary (no DB required)."""
    logger.info("Parsing Transaction file: %s", filepath)
    records = parse_transaction_file(filepath)
    if not records:
        logger.error("No records parsed from Transaction file!")
        return

    clients = set(r["client_code"] for r in records)
    txn_types = {}
    for r in records:
        t = r["txn_type"]
        txn_types[t] = txn_types.get(t, 0) + 1

    logger.info(
        "Parsed %d transaction records for %d clients", len(records), len(clients)
    )
    logger.info("Transaction types: %s", txn_types)

    # Show first client's data
    first_client = records[0]["client_code"]
    client_records = [r for r in records if r["client_code"] == first_client]
    logger.info(
        "Sample — Client %s: %d transactions",
        first_client,
        len(client_records),
    )


async def full_ingest(nav_path: str | None, txn_path: str | None) -> None:
    """Full ingestion with database writes."""
    from backend.database import get_db_session
    from backend.services.ingestion_service import (
        ingest_nav_file,
        ingest_transaction_file,
    )

    async with get_db_session() as session:
        if nav_path:
            logger.info("=== Ingesting NAV file ===")
            result = await ingest_nav_file(nav_path, uploaded_by=None, db=session)
            logger.info("NAV ingestion result: %s", result)

        if txn_path:
            logger.info("=== Ingesting Transaction file ===")
            result = await ingest_transaction_file(
                txn_path, uploaded_by=None, db=session
            )
            logger.info("Transaction ingestion result: %s", result)


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest PMS data files")
    parser.add_argument("--nav", type=str, help="Path to NAV .xlsx file")
    parser.add_argument("--txn", type=str, help="Path to Transaction .xlsx file")
    parser.add_argument(
        "--test-only",
        action="store_true",
        help="Parse and print summary only, no DB writes",
    )
    args = parser.parse_args()

    if not args.nav and not args.txn:
        parser.error("Provide at least one of --nav or --txn")

    if args.test_only:
        if args.nav:
            test_parse_nav(args.nav)
        if args.txn:
            test_parse_txn(args.txn)
    else:
        asyncio.run(full_ingest(args.nav, args.txn))


if __name__ == "__main__":
    main()
