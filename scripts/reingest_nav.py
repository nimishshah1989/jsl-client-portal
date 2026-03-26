"""Re-ingest NAV file to populate etf_value, cash_value, bank_balance columns.

Run locally: python -m scripts.reingest_nav
Uses the NAV parser + direct DB connection to upsert all rows.
"""

import asyncio
import logging
import sys
from pathlib import Path

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.services.nav_parser import parse_nav_file
from backend.services.ingestion_helpers import (
    find_or_create_client,
    find_or_create_portfolio,
    upsert_nav_rows,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

DATABASE_URL = (
    "postgresql+asyncpg://fie_admin:Nimish1234"
    "@fie-db.c7osw6q6kwmw.ap-south-1.rds.amazonaws.com:5432/client_portal"
)

NAV_FILE = Path(__file__).resolve().parent.parent / "data" / "NAV Report-01-04-2020 to 16-03-2026.xlsx"


async def main():
    if not NAV_FILE.exists():
        logger.error("NAV file not found: %s", NAV_FILE)
        return

    logger.info("Parsing NAV file: %s", NAV_FILE.name)
    records = parse_nav_file(NAV_FILE)
    logger.info("Parsed %d records", len(records))

    # Group by client
    by_client: dict[str, list[dict]] = {}
    for rec in records:
        code = rec["client_code"]
        by_client.setdefault(code, []).append(rec)

    logger.info("Clients found: %d", len(by_client))

    engine = create_async_engine(DATABASE_URL, pool_size=5)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    total_upserted = 0
    client_count = 0

    async with async_session() as db:
        for code, client_records in by_client.items():
            client_count += 1
            name = client_records[0]["client_name"]
            client_id = await find_or_create_client(db, code, name)
            inception = client_records[0]["date"]
            portfolio_id = await find_or_create_portfolio(db, client_id, inception)
            count = await upsert_nav_rows(db, client_id, portfolio_id, client_records)
            total_upserted += count

            if client_count % 50 == 0:
                await db.commit()
                logger.info("Progress: %d/%d clients, %d rows", client_count, len(by_client), total_upserted)

        await db.commit()

    await engine.dispose()
    logger.info("Done. Upserted %d NAV rows across %d clients.", total_upserted, client_count)


if __name__ == "__main__":
    asyncio.run(main())
