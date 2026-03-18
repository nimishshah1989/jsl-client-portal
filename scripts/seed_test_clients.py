"""
Seed 3 test clients with synthetic NAV data and transactions.

Usage:
    python scripts/seed_test_clients.py

Requires DATABASE_URL_SYNC or DATABASE_URL in .env.
Outputs generated credentials to stdout.
"""

import os
import sys
import random
import math
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

# Add project root to path for imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from passlib.hash import bcrypt as bcrypt_hash
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

# Load .env manually for standalone script
from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent / ".env")


DB_URL = os.getenv("DATABASE_URL_SYNC") or os.getenv("DATABASE_URL", "")
if "asyncpg" in DB_URL:
    DB_URL = DB_URL.replace("postgresql+asyncpg://", "postgresql://")

if not DB_URL:
    print("ERROR: DATABASE_URL_SYNC or DATABASE_URL not set in .env")
    sys.exit(1)

engine = create_engine(DB_URL, echo=False)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)

BCRYPT_ROUNDS = 12

TEST_CLIENTS = [
    {
        "client_code": "TC01",
        "name": "Test Client Alpha",
        "email": "alpha@test.jslwealth.in",
        "phone": "+91 98765 00001",
        "username": "tc01",
        "password": "alpha2026!",
        "is_admin": False,
        "nav_days": 730,   # ~2 years
        "txn_count": 50,
    },
    {
        "client_code": "TC02",
        "name": "Test Client Beta",
        "email": "beta@test.jslwealth.in",
        "phone": "+91 98765 00002",
        "username": "tc02",
        "password": "beta2026!!",
        "is_admin": False,
        "nav_days": 365,   # ~1 year
        "txn_count": 30,
    },
    {
        "client_code": "ADMIN",
        "name": "Admin User",
        "email": "admin@jslwealth.in",
        "phone": "+91 98765 00000",
        "username": "admin",
        "password": "admin123",
        "is_admin": True,
        "nav_days": 0,
        "txn_count": 0,
    },
]

STOCK_SYMBOLS = [
    ("RELIANCE", "Reliance Industries", "Equity"),
    ("TCS", "Tata Consultancy Services", "Equity"),
    ("HDFCBANK", "HDFC Bank", "Equity"),
    ("INFY", "Infosys", "Equity"),
    ("ICICIBANK", "ICICI Bank", "Equity"),
    ("HINDUNILVR", "Hindustan Unilever", "Equity"),
    ("ITC", "ITC Ltd", "Equity"),
    ("SBIN", "State Bank of India", "Equity"),
    ("BHARTIARTL", "Bharti Airtel", "Equity"),
    ("LIQUIDBEES", "Liquid BeES", "CASH"),
]


def hash_password(plain: str) -> str:
    """Hash password with bcrypt cost factor 12."""
    return bcrypt_hash.using(rounds=BCRYPT_ROUNDS).hash(plain)


def generate_nav_series(start_date: date, num_days: int) -> list[dict]:
    """
    Generate a realistic NAV curve: trending up with drawdowns.
    Returns list of dicts with nav_date, nav_value, cash_pct, corpus.
    """
    navs = []
    base_value = Decimal("3333333")  # ~33.3L starting corpus
    current_value = float(base_value)
    corpus = float(base_value)

    # Parameters for realistic returns
    annual_drift = 0.15   # 15% annual expected return
    daily_drift = annual_drift / 252
    daily_vol = 0.012     # ~19% annualized vol

    d = start_date
    day_count = 0

    while day_count < num_days:
        # Skip weekends
        if d.weekday() >= 5:
            d += timedelta(days=1)
            continue

        # Random daily return with slight upward bias
        daily_ret = random.gauss(daily_drift, daily_vol)

        # Occasional drawdown events (~2% chance of a bad day)
        if random.random() < 0.02:
            daily_ret = random.gauss(-0.03, 0.015)

        current_value *= (1 + daily_ret)
        current_value = max(current_value, corpus * 0.5)  # Floor at 50% of corpus

        # Simulate corpus change (~5% chance on any given day in first quarter)
        if day_count < num_days // 4 and random.random() < 0.002:
            infusion = random.choice([200000, 500000, 1000000])
            corpus += infusion
            current_value += infusion

        cash_pct = random.uniform(2.0, 25.0)

        navs.append({
            "nav_date": d,
            "nav_value": Decimal(str(round(current_value, 2))),
            "cash_pct": Decimal(str(round(cash_pct, 2))),
            "corpus": Decimal(str(round(corpus, 2))),
        })

        d += timedelta(days=1)
        day_count += 1

    return navs


def generate_transactions(
    start_date: date, count: int
) -> list[dict]:
    """Generate synthetic buy/sell transactions."""
    txns = []
    d = start_date + timedelta(days=random.randint(1, 30))

    for i in range(count):
        # Skip weekends
        while d.weekday() >= 5:
            d += timedelta(days=1)

        sym_tuple = random.choice(STOCK_SYMBOLS)
        symbol, asset_name, asset_class = sym_tuple
        is_buy = random.random() < 0.65  # 65% buys

        quantity = random.randint(1, 200) * 5
        price = Decimal(str(round(random.uniform(100, 5000), 2)))
        amount = (price * quantity).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        txn_type = "BUY" if is_buy else "SELL"
        if i < 3:
            txn_type = "BUY"  # Ensure initial buys

        txns.append({
            "txn_date": d,
            "txn_type": txn_type,
            "symbol": symbol,
            "asset_name": asset_name,
            "asset_class": asset_class,
            "quantity": Decimal(str(quantity)),
            "price": price,
            "amount": amount,
        })

        d += timedelta(days=random.randint(1, 20))

    return txns


def generate_benchmark_values(navs: list[dict]) -> list[Decimal]:
    """Generate Nifty-like benchmark values aligned to NAV dates."""
    if not navs:
        return []

    bench_start = 18000.0
    current = bench_start
    values = []

    daily_drift = 0.10 / 252  # 10% annual benchmark return
    daily_vol = 0.014

    for _ in navs:
        ret = random.gauss(daily_drift, daily_vol)
        current *= (1 + ret)
        values.append(Decimal(str(round(current, 4))))

    return values


def seed_client(session: Session, client_cfg: dict) -> None:
    """Insert client, portfolio, NAV series, and transactions."""
    code = client_cfg["client_code"]
    pw_hash = hash_password(client_cfg["password"])

    # Upsert client
    session.execute(text("""
        INSERT INTO cpp_clients (client_code, name, email, phone, username, password_hash, is_active, is_admin)
        VALUES (:code, :name, :email, :phone, :username, :pw_hash, true, :is_admin)
        ON CONFLICT (client_code) DO UPDATE SET
            name = EXCLUDED.name,
            password_hash = EXCLUDED.password_hash,
            is_admin = EXCLUDED.is_admin
    """), {
        "code": code,
        "name": client_cfg["name"],
        "email": client_cfg["email"],
        "phone": client_cfg["phone"],
        "username": client_cfg["username"],
        "pw_hash": pw_hash,
        "is_admin": client_cfg["is_admin"],
    })
    session.flush()

    # Get client_id
    row = session.execute(
        text("SELECT id FROM cpp_clients WHERE client_code = :code"),
        {"code": code},
    ).fetchone()
    client_id = row[0]

    if client_cfg["nav_days"] == 0:
        return  # Admin-only, no portfolio data

    # Create portfolio
    today = date.today()
    inception = today - timedelta(days=client_cfg["nav_days"])

    session.execute(text("""
        INSERT INTO cpp_portfolios (client_id, portfolio_name, benchmark, inception_date, status)
        VALUES (:cid, 'PMS Equity', 'NIFTY500', :inception, 'active')
        ON CONFLICT DO NOTHING
    """), {"cid": client_id, "inception": inception})
    session.flush()

    port_row = session.execute(
        text("SELECT id FROM cpp_portfolios WHERE client_id = :cid LIMIT 1"),
        {"cid": client_id},
    ).fetchone()
    portfolio_id = port_row[0]

    # Generate and insert NAV series
    navs = generate_nav_series(inception, client_cfg["nav_days"])
    bench_values = generate_benchmark_values(navs)

    for i, nav in enumerate(navs):
        session.execute(text("""
            INSERT INTO cpp_nav_series
                (client_id, portfolio_id, nav_date, nav_value, invested_amount, current_value, benchmark_value, cash_pct)
            VALUES
                (:cid, :pid, :nav_date, :nav_value, :corpus, :current_value, :bench, :cash_pct)
            ON CONFLICT (client_id, portfolio_id, nav_date) DO UPDATE SET
                nav_value = EXCLUDED.nav_value,
                invested_amount = EXCLUDED.invested_amount,
                current_value = EXCLUDED.current_value,
                benchmark_value = EXCLUDED.benchmark_value,
                cash_pct = EXCLUDED.cash_pct
        """), {
            "cid": client_id,
            "pid": portfolio_id,
            "nav_date": nav["nav_date"],
            "nav_value": nav["nav_value"],
            "corpus": nav["corpus"],
            "current_value": nav["nav_value"],
            "bench": bench_values[i],
            "cash_pct": nav["cash_pct"],
        })

    # Generate and insert transactions
    txns = generate_transactions(inception, client_cfg["txn_count"])

    for txn in txns:
        session.execute(text("""
            INSERT INTO cpp_transactions
                (client_id, portfolio_id, txn_date, txn_type, symbol, asset_name, asset_class, quantity, price, amount)
            VALUES
                (:cid, :pid, :txn_date, :txn_type, :symbol, :asset_name, :asset_class, :qty, :price, :amount)
        """), {
            "cid": client_id,
            "pid": portfolio_id,
            "txn_date": txn["txn_date"],
            "txn_type": txn["txn_type"],
            "symbol": txn["symbol"],
            "asset_name": txn["asset_name"],
            "asset_class": txn["asset_class"],
            "qty": txn["quantity"],
            "price": txn["price"],
            "amount": txn["amount"],
        })


def main() -> None:
    """Seed all test clients."""
    print("=" * 60)
    print("JSL Client Portfolio Portal — Test Data Seeder")
    print("=" * 60)
    print(f"Database: {DB_URL[:50]}...")
    print()

    session = SessionLocal()
    try:
        for cfg in TEST_CLIENTS:
            print(f"Seeding: {cfg['name']} [{cfg['client_code']}]...")
            seed_client(session, cfg)
            print(f"  NAV days: {cfg['nav_days']}, Transactions: {cfg['txn_count']}")

        session.commit()
        print()
        print("All clients seeded successfully.")
        print()
        print("-" * 60)
        print("CREDENTIALS (save these — passwords are hashed in DB)")
        print("-" * 60)
        print(f"{'Username':<15} {'Password':<20} {'Role'}")
        print(f"{'--------':<15} {'--------':<20} {'----'}")
        for cfg in TEST_CLIENTS:
            role = "Admin" if cfg["is_admin"] else "Client"
            print(f"{cfg['username']:<15} {cfg['password']:<20} {role}")
        print("-" * 60)

    except Exception as e:
        session.rollback()
        print(f"ERROR: {e}")
        raise
    finally:
        session.close()


if __name__ == "__main__":
    main()
