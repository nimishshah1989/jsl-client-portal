"""Tests for the unified-login merge service (PR7a).

The rigor: seed a production-shaped mini-DB (a multi-code person + a single-code
person + a closed account + an admin + a soft-deleted client, each with rows in
EVERY per-client data table), capture the baseline, run the REAL migration on it,
and assert every invariant holds + a retired login resolves to the survivor.

This runs in CI (it is the gate that must pass before the migration ever touches
prod). It exercises the same merge_service code path the prod CLI runs.
"""

import os

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("JWT_SECRET", "a" * 64)

import datetime as dt
import tempfile
from decimal import Decimal
from types import SimpleNamespace

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from backend.database import Base
from backend.models.cash_flow import CashFlow
from backend.models.client import Client
from backend.models.drawdown import DrawdownSeries
from backend.models.holding import Holding
from backend.models.merge_audit import MergeAudit
from backend.models.nav_series import NavSeries
from backend.models.portfolio import Portfolio
from backend.models.risk_metric import RiskMetric
from backend.models.transaction import Transaction
from backend.services.merge_service import (
    MergeInvariantError,
    capture_baseline,
    merge_clients_by_name,
    pick_survivor,
    resolve_login_target,
    verify_merge_invariants,
)

JHAVERI = "BHADRESH JITENDRA JHAVERI"

# ── Expected, hand-computed baseline for the seeded fixture ──
# latest nav_value per portfolio:  120000 + 55000 + 28000(closed) + 250000
EXPECTED_AUM = Decimal("453000.00")
# latest invested per portfolio:   100000 +  50000 + 30000(closed) + 200000
EXPECTED_INVESTED = Decimal("380000.00")
EXPECTED_PORTFOLIOS = 4


# ──────────────────────────────────────────────────────────────────────────────
# Pure: pick_survivor
# ──────────────────────────────────────────────────────────────────────────────

def _m(id, last_login):
    return SimpleNamespace(id=id, last_login=last_login)


class TestPickSurvivor:
    def test_most_recent_login_wins(self):
        members = [
            _m(1, dt.datetime(2020, 1, 1)),
            _m(2, dt.datetime(2026, 5, 1)),  # most recent
            _m(3, dt.datetime(2024, 1, 1)),
        ]
        assert pick_survivor(members).id == 2

    def test_logged_in_beats_never_logged_in(self):
        members = [_m(1, None), _m(2, None), _m(3, dt.datetime(2021, 1, 1))]
        assert pick_survivor(members).id == 3

    def test_all_never_logged_in_breaks_to_lowest_id(self):
        members = [_m(7, None), _m(3, None), _m(5, None)]
        assert pick_survivor(members).id == 3

    def test_equal_logins_break_to_lowest_id(self):
        when = dt.datetime(2025, 1, 1)
        members = [_m(9, when), _m(4, when), _m(6, when)]
        assert pick_survivor(members).id == 4

    def test_single_member(self):
        assert pick_survivor([_m(42, None)]).id == 42

    def test_empty_raises(self):
        with pytest.raises(ValueError):
            pick_survivor([])

    def test_tz_aware_and_naive_mix(self):
        aware = dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc)
        naive_earlier = dt.datetime(2025, 1, 1)
        assert pick_survivor([_m(1, naive_earlier), _m(2, aware)]).id == 2


# ──────────────────────────────────────────────────────────────────────────────
# Production-shaped fixture
# ──────────────────────────────────────────────────────────────────────────────

@pytest_asyncio.fixture(scope="function")
async def seeded():
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp.name}")
    tables = [
        Client.__table__, Portfolio.__table__, NavSeries.__table__,
        Transaction.__table__, Holding.__table__, RiskMetric.__table__,
        DrawdownSeries.__table__, CashFlow.__table__, MergeAudit.__table__,
    ]
    async with engine.begin() as conn:
        await conn.run_sync(lambda c: Base.metadata.create_all(c, tables=tables))

    Session = async_sessionmaker(bind=engine, expire_on_commit=False)
    async with Session() as s:
        # Clients — three share a name (the multi-code person), one single-code
        # person, one admin with the SAME name (must NOT be merged), one deleted.
        s.add_all([
            Client(id=1, client_code="BJ53", name=JHAVERI, username="bj53",
                   password_hash="x", is_active=True, is_admin=False,
                   last_login=dt.datetime(2026, 5, 1)),           # survivor
            Client(id=2, client_code="BJ53PASS", name=JHAVERI, username="bj53pass",
                   password_hash="x", is_active=True, is_admin=False,
                   last_login=None),                              # retired (alias)
            Client(id=3, client_code="BJ53CLOSE", name=JHAVERI, username="bj53close",
                   password_hash="x", is_active=True, is_admin=False,
                   last_login=None),                              # retired (closed acct)
            Client(id=4, client_code="JEET01", name="JEET SHAH", username="jeet01",
                   password_hash="x", is_active=True, is_admin=False,
                   last_login=dt.datetime(2026, 4, 1)),           # single-code, untouched
            Client(id=5, client_code="ADMINBJ", name=JHAVERI, username="adminbj",
                   password_hash="x", is_active=True, is_admin=True),  # admin, excluded
            # Soft-deleted, SAME name, and the MOST RECENT login: if the is_deleted
            # filter ever broke, this would wrongly be picked as survivor.
            Client(id=6, client_code="BJ53OLD", name=JHAVERI, username="bj53old",
                   password_hash="x", is_active=False, is_admin=False, is_deleted=True,
                   last_login=dt.datetime(2026, 12, 1)),
        ])

        # Portfolios — ALL named "PMS Equity" (production reality → the rename trap).
        s.add_all([
            Portfolio(id=10, client_id=1, portfolio_name="PMS Equity", client_code="BJ53",
                      strategy="LEADERS", is_closed=False, inception_date=dt.date(2024, 1, 1)),
            Portfolio(id=11, client_id=2, portfolio_name="PMS Equity", client_code="BJ53PASS",
                      strategy="PASSIVE", is_closed=False, inception_date=dt.date(2024, 1, 1)),
            Portfolio(id=12, client_id=3, portfolio_name="PMS Equity", client_code="BJ53CLOSE",
                      strategy="LEADERS", is_closed=True, inception_date=dt.date(2024, 1, 1)),
            Portfolio(id=13, client_id=4, portfolio_name="PMS Equity", client_code="JEET01",
                      strategy="LEADERS", is_closed=False, inception_date=dt.date(2024, 1, 1)),
        ])
        await s.flush()

        # (owner_client_id, portfolio_id, latest_nav, invested)
        plan = [
            (1, 10, "120000", "100000", ("100000", "120000")),
            (2, 11, "55000", "50000", ("50000", "55000")),
            (3, 12, "28000", "30000", ("30000", "28000")),  # closed
            (4, 13, "250000", "200000", ("200000", "250000")),
        ]
        d1, d2 = dt.date(2024, 1, 1), dt.date(2024, 6, 1)
        for cid, pid, _latest, inv, (nav1, nav2) in plan:
            for d, navv in ((d1, nav1), (d2, nav2)):
                s.add(NavSeries(
                    client_id=cid, portfolio_id=pid, nav_date=d,
                    nav_value=Decimal(navv), current_value=Decimal(navv),
                    invested_amount=Decimal(inv), benchmark_value=Decimal("21000"),
                ))
            # A row in EVERY per-client data table so the migration moves real data.
            s.add(Transaction(
                client_id=cid, portfolio_id=pid, txn_date=d1, txn_type="BUY",
                symbol="RELIANCE", asset_class="EQUITY", quantity=Decimal("10"),
                price=Decimal("100"), amount=Decimal("1000"),
            ))
            s.add(Holding(
                client_id=cid, portfolio_id=pid, symbol="RELIANCE",
                quantity=Decimal("10"), avg_cost=Decimal("100"),
                current_price=Decimal("120"), current_value=Decimal("1200"),
                unrealized_pnl=Decimal("200"),
            ))
            s.add(RiskMetric(
                client_id=cid, portfolio_id=pid, computed_date=d2,
                cagr=Decimal("12.0"),
            ))
            s.add(DrawdownSeries(
                client_id=cid, portfolio_id=pid, dd_date=d2,
                drawdown_pct=Decimal("-5.0"), peak_nav=Decimal("120000"),
                current_nav=Decimal("114000"),
            ))
            s.add(CashFlow(
                client_id=cid, portfolio_id=pid, flow_date=d1,
                flow_type="INFLOW", amount=Decimal(inv),
            ))
        await s.commit()

    try:
        yield Session
    finally:
        await engine.dispose()


async def _count(s, model, **eq):
    stmt = select(func.count()).select_from(model)
    for col, val in eq.items():
        stmt = stmt.where(getattr(model, col) == val)
    return int((await s.execute(stmt)).scalar() or 0)


# ──────────────────────────────────────────────────────────────────────────────
# Baseline
# ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_baseline_matches_hand_computed(seeded):
    async with seeded() as s:
        base = await capture_baseline(s)
    assert base["total_aum"] == EXPECTED_AUM
    assert base["total_invested"] == EXPECTED_INVESTED
    assert base["portfolio_count"] == EXPECTED_PORTFOLIOS


# ──────────────────────────────────────────────────────────────────────────────
# Dry run writes nothing
# ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_dry_run_writes_nothing(seeded):
    async with seeded() as s:
        report = await merge_clients_by_name(s, dry_run=True)
        await s.rollback()

    # Plan is correct...
    assert report["dry_run"] is True
    assert report["totals"]["multi_code_groups"] == 1
    assert report["totals"]["codes_retired"] == 2
    assert report["totals"]["portfolios_reparented"] == 2
    # ...but nothing was written (fresh session reads committed DB state).
    async with seeded() as s:
        assert await _count(s, Client, merged_into=1) == 0
        assert await _count(s, MergeAudit) == 0


# ──────────────────────────────────────────────────────────────────────────────
# The real migration + every invariant
# ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_real_migration_holds_every_invariant(seeded):
    # Run the real migration exactly as the CLI does: baseline → merge → flush →
    # verify (recon-before-commit) → commit.
    async with seeded() as s:
        baseline = await capture_baseline(s)
        report = await merge_clients_by_name(s, dry_run=False)
        await s.flush()
        verify_report = await verify_merge_invariants(s, baseline)
        await s.commit()

    assert verify_report["ok"] is True
    assert report["totals"]["codes_retired"] == 2

    # Assert on committed state via a fresh session (no stale identity map).
    async with seeded() as s:
        # Survivor selection: BJ53 (the only one with a last_login).
        assert (await s.get(Client, 2)).merged_into == 1
        assert (await s.get(Client, 3)).merged_into == 1
        assert (await s.get(Client, 1)).merged_into is None       # survivor
        assert (await s.get(Client, 4)).merged_into is None       # single-code, untouched
        assert (await s.get(Client, 5)).merged_into is None       # admin, excluded
        assert (await s.get(Client, 6)).merged_into is None       # soft-deleted, excluded

        # Survivor now owns its own + the two re-parented portfolios; JEET keeps his.
        assert await _count(s, Portfolio, client_id=1) == 3
        assert await _count(s, Portfolio, client_id=2) == 0
        assert await _count(s, Portfolio, client_id=3) == 0
        assert await _count(s, Portfolio, client_id=4) == 1

        # Re-parented portfolios got unique, collision-proof names.
        names = {p.id: p.portfolio_name for p in (await s.execute(
            select(Portfolio).where(Portfolio.client_id == 1)
        )).scalars().all()}
        assert names[10] == "PMS Equity"
        assert names[11] == "PMS Equity (BJ53PASS)"
        assert names[12] == "PMS Equity (BJ53CLOSE)"

        # Every data table re-parented onto the survivor (none left on 2/3).
        # JEET (single-code) is untouched: 2 NAV rows per portfolio, 1 in the rest.
        jeet_expected = {NavSeries: 2, Transaction: 1, Holding: 1,
                         RiskMetric: 1, DrawdownSeries: 1, CashFlow: 1}
        for model in (NavSeries, Transaction, Holding, RiskMetric, DrawdownSeries, CashFlow):
            assert await _count(s, model, client_id=2) == 0, model.__tablename__
            assert await _count(s, model, client_id=3) == 0, model.__tablename__
            assert await _count(s, model, client_id=4) == jeet_expected[model], model.__tablename__

        # Cross-table ownership: every data row's client_id == its portfolio owner.
        for model in (NavSeries, Transaction, Holding, RiskMetric, DrawdownSeries, CashFlow):
            mism = (await s.execute(
                select(func.count()).select_from(model)
                .join(Portfolio, Portfolio.id == model.portfolio_id)
                .where(model.client_id != Portfolio.client_id)
            )).scalar() or 0
            assert mism == 0, f"{model.__tablename__} ownership drift"

        # AUM / invested / portfolio count invariant (the merge moved no money).
        after = await capture_baseline(s)
        assert after["total_aum"] == EXPECTED_AUM
        assert after["total_invested"] == EXPECTED_INVESTED
        assert after["portfolio_count"] == EXPECTED_PORTFOLIOS

        # Audit trail: one row per retired client, mapping to the survivor.
        audit = (await s.execute(select(MergeAudit).order_by(MergeAudit.retired_id))).scalars().all()
        assert [(a.retired_id, a.survivor_id, a.retired_code) for a in audit] == [
            (2, 1, "BJ53PASS"), (3, 1, "BJ53CLOSE"),
        ]


@pytest.mark.asyncio
async def test_retired_login_resolves_to_survivor(seeded):
    async with seeded() as s:
        await merge_clients_by_name(s, dry_run=False)
        await s.commit()

    async with seeded() as s:
        retired = await s.get(Client, 2)          # BJ53PASS — a retired alias
        survivor = await resolve_login_target(s, retired)
        assert survivor.id == 1
        assert survivor.client_code == "BJ53"
        # Survivor's portfolios load eagerly (no async lazy-load error) for the
        # LoginResponse.portfolio_count.
        assert len(survivor.portfolios) == 3

        # A normal (un-merged) login resolves to itself.
        jeet = await s.get(Client, 4)
        assert (await resolve_login_target(s, jeet)).id == 4
        # The survivor itself resolves to itself.
        bj53 = await s.get(Client, 1)
        assert (await resolve_login_target(s, bj53)).id == 1

    # If the unified (survivor) account is unavailable, DENY rather than strand the
    # user on the now-empty retired account: resolve returns None.
    async with seeded() as s:
        survivor = await s.get(Client, 1)
        survivor.is_active = False
        await s.commit()
    async with seeded() as s:
        retired = await s.get(Client, 2)
        assert await resolve_login_target(s, retired) is None


@pytest.mark.asyncio
async def test_resolve_follows_chain_and_refuses_cycle(seeded):
    async with seeded() as s:
        await merge_clients_by_name(s, dry_run=False)
        await s.commit()

    # Build a multi-round chain 2 -> 1 -> 4 (JEET, active): an alias on 2 must land
    # on the terminal survivor 4, not the intermediate 1.
    async with seeded() as s:
        one = await s.get(Client, 1)
        one.merged_into = 4
        await s.commit()
    async with seeded() as s:
        assert (await resolve_login_target(s, await s.get(Client, 2))).id == 4

    # A cycle (1 -> 4 -> 1) must be refused, not looped.
    async with seeded() as s:
        four = await s.get(Client, 4)
        four.merged_into = 1
        await s.commit()
    async with seeded() as s:
        assert await resolve_login_target(s, await s.get(Client, 2)) is None


@pytest.mark.asyncio
async def test_migration_is_idempotent(seeded):
    async with seeded() as s:
        await merge_clients_by_name(s, dry_run=False)
        await s.commit()

    # Second run finds nothing to do (retired clients are filtered out, and the
    # survivor's name-group is now single-member).
    async with seeded() as s:
        baseline = await capture_baseline(s)
        report = await merge_clients_by_name(s, dry_run=False)
        await s.flush()
        verify_report = await verify_merge_invariants(s, baseline)
        await s.commit()

    assert report["totals"]["multi_code_groups"] == 0
    assert report["totals"]["codes_retired"] == 0
    assert verify_report["ok"] is True


@pytest.mark.asyncio
async def test_verify_raises_on_injected_drift(seeded):
    # Sanity-check that verify actually fails when an invariant is violated:
    # capture a baseline, then corrupt AUM by deleting a NAV row before verifying.
    async with seeded() as s:
        baseline = await capture_baseline(s)
        await merge_clients_by_name(s, dry_run=False)
        await s.flush()
        # Inject drift: drop the survivor's latest NAV row → AUM falls.
        from sqlalchemy import delete
        await s.execute(
            delete(NavSeries).where(
                NavSeries.portfolio_id == 10, NavSeries.nav_date == dt.date(2024, 6, 1)
            )
        )
        await s.flush()
        with pytest.raises(MergeInvariantError):
            await verify_merge_invariants(s, baseline)
        await s.rollback()


# ──────────────────────────────────────────────────────────────────────────────
# Per-request auth alias (a retired session must land on the survivor)
# ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_retired_session_resolves_to_survivor_per_request(seeded):
    """A JWT for a retired (merged_into) client resolves to the survivor on every
    request — so a stale/grace-period session lands on the one unified account,
    not the emptied retired one (the blank-dashboard bug)."""
    from backend.middleware.auth_middleware import _validate_client_from_db
    async with seeded() as s:
        # Post-merge state: retire client 2 (BJ53PASS) onto survivor 1 (BJ53).
        (await s.execute(select(Client).where(Client.id == 2))).scalar_one().merged_into = 1
        await s.commit()

        retired = await _validate_client_from_db(
            {"client_id": 2, "token_version": 1, "is_admin": False}, s)
        assert retired["client_id"] == 1            # followed alias → survivor

        survivor = await _validate_client_from_db(
            {"client_id": 1, "token_version": 1, "is_admin": False}, s)
        assert survivor["client_id"] == 1           # survivor unchanged

        single = await _validate_client_from_db(
            {"client_id": 4, "token_version": 1, "is_admin": False}, s)
        assert single["client_id"] == 4             # un-merged client unchanged


@pytest.mark.asyncio
async def test_retired_session_denied_when_survivor_unavailable(seeded):
    """Deny (401), never strand: if the survivor is inactive/deleted, a retired
    session is rejected rather than landing on the empty retired account."""
    from fastapi import HTTPException
    from backend.middleware.auth_middleware import _validate_client_from_db
    async with seeded() as s:
        (await s.execute(select(Client).where(Client.id == 2))).scalar_one().merged_into = 1
        (await s.execute(select(Client).where(Client.id == 1))).scalar_one().is_active = False
        await s.commit()
        with pytest.raises(HTTPException) as ei:
            await _validate_client_from_db(
                {"client_id": 2, "token_version": 1, "is_admin": False}, s)
        assert ei.value.status_code == 401


@pytest.mark.asyncio
async def test_admin_client_list_hides_merged_aliases(seeded):
    """After the merge, the admin client list shows one row per person (the
    survivor) — retired per-code aliases are hidden, and the survivor's
    portfolio_count reflects every re-parented sleeve."""
    from backend.routers.admin_clients import list_clients
    async with seeded() as s:
        await merge_clients_by_name(s, dry_run=False)
        await s.commit()
        rows = await list_clients(admin={"client_id": 1, "is_admin": True}, db=s)
        ids = {r.id for r in rows}
        # Retired aliases (BJ53PASS=2, BJ53CLOSE=3) and soft-deleted (6) are gone.
        assert ids.isdisjoint({2, 3, 6})
        # Survivor BJ53 (id=1) appears once, owning its re-parented sleeves.
        survivors = [r for r in rows if r.id == 1]
        assert len(survivors) == 1
        assert survivors[0].portfolio_count >= 2
        # Untouched single-code person still listed.
        assert 4 in ids
