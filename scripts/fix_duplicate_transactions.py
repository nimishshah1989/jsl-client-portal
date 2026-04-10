"""
One-time fix: remove duplicate transactions and add unique constraint.

Run: python -m scripts.fix_duplicate_transactions

This script:
1. Counts duplicates
2. Deletes excess rows (keeps the one with lowest id per group)
3. Adds unique constraint to prevent future duplicates
4. Recomputes holdings for all affected clients
"""

import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import text

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

DATABASE_URL = (
    "postgresql+asyncpg://fie_admin:Nimish1234"
    "@fie-db.c7osw6q6kwmw.ap-south-1.rds.amazonaws.com:5432/client_portal"
)


async def main():
    engine = create_async_engine(DATABASE_URL, pool_size=5)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as db:
        # Step 1: Count
        r = await db.execute(text("SELECT COUNT(*) FROM cpp_transactions"))
        total_before = r.scalar()
        logger.info("Total transactions before: %d", total_before)

        r = await db.execute(text("""
            SELECT SUM(cnt - 1) FROM (
                SELECT COUNT(*) as cnt FROM cpp_transactions
                GROUP BY client_id, portfolio_id, txn_date, txn_type, symbol,
                         quantity, price, settlement_no
                HAVING COUNT(*) > 1
            ) d
        """))
        excess = r.scalar() or 0
        logger.info("Excess duplicate rows to delete: %d", excess)

        if excess == 0:
            logger.info("No duplicates found. Nothing to do.")
            await engine.dispose()
            return

        # Step 2: Delete duplicates
        logger.info("Deleting duplicates (keeping lowest id per group)...")
        await db.execute(text("""
            DELETE FROM cpp_transactions
            WHERE id NOT IN (
                SELECT MIN(id)
                FROM cpp_transactions
                GROUP BY client_id, portfolio_id, txn_date, txn_type, symbol,
                         quantity, price, settlement_no
            )
        """))
        await db.commit()

        r = await db.execute(text("SELECT COUNT(*) FROM cpp_transactions"))
        total_after = r.scalar()
        logger.info("Total transactions after: %d (deleted %d)", total_after, total_before - total_after)

        # Step 3: Add unique constraint (if not exists)
        r = await db.execute(text("""
            SELECT 1 FROM pg_constraint WHERE conname = 'uq_cpp_txn_dedup'
        """))
        if r.fetchone() is None:
            logger.info("Adding unique constraint uq_cpp_txn_dedup...")
            await db.execute(text("""
                ALTER TABLE cpp_transactions ADD CONSTRAINT uq_cpp_txn_dedup
                UNIQUE (client_id, portfolio_id, txn_date, txn_type, symbol,
                        quantity, price, settlement_no)
            """))
            await db.commit()
            logger.info("Unique constraint added.")
        else:
            logger.info("Unique constraint already exists.")

        # Step 4: Recompute holdings for all clients
        logger.info("Recomputing holdings for all clients...")
        from backend.services.ingestion_helpers import recompute_holdings

        r = await db.execute(text("""
            SELECT DISTINCT c.id, p.id, c.client_code
            FROM cpp_clients c
            JOIN cpp_portfolios p ON p.client_id = c.id
            WHERE c.is_active = true
            ORDER BY c.client_code
        """))
        pairs = r.fetchall()

        success = 0
        for client_id, portfolio_id, code in pairs:
            try:
                count = await recompute_holdings(db, client_id, portfolio_id)
                await db.commit()
                success += 1
                if success % 50 == 0:
                    logger.info("  Recomputed holdings: %d/%d", success, len(pairs))
            except Exception as e:
                logger.error("  Failed %s: %s", code, e)
                await db.rollback()

        logger.info("Holdings recomputed for %d/%d clients", success, len(pairs))

        # Verify
        r = await db.execute(text("""
            SELECT COUNT(*) FROM (
                SELECT 1 FROM cpp_transactions
                GROUP BY client_id, portfolio_id, txn_date, txn_type, symbol,
                         quantity, price, settlement_no
                HAVING COUNT(*) > 1
            ) d
        """))
        remaining = r.scalar()
        logger.info("Remaining duplicate groups: %d", remaining)

    await engine.dispose()
    logger.info("Done.")


if __name__ == "__main__":
    asyncio.run(main())
