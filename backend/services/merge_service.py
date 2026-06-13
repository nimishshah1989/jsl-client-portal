"""Unified-login merge service (PR7a).

Collapses several per-code clients that are the *same person* (grouped by exact
full name) into a single survivor, re-parenting every owned row — the portfolios
and all per-client data (NAV series, transactions, holdings, risk metrics,
drawdown series, cash flows) — onto the survivor, then soft-retiring the
non-survivors via ``merged_into`` and writing an audit trail.

Design guarantees
-----------------
* **Pure survivor pick** — ``pick_survivor`` is deterministic and side-effect-free.
* **One transaction** — ``merge_clients_by_name`` performs every write through the
  caller's session and flushes, but never commits; the caller commits only after
  ``verify_merge_invariants`` passes (reconcile-before-commit).
* **Reversible** — non-survivors are soft-retired (``merged_into`` set, ``is_active``
  untouched) and every fold is recorded in ``cpp_merge_audit``. No row is deleted.
* **Invariant-preserving** — the merge only changes ``client_id`` (and, to satisfy
  the ``(client_id, portfolio_name)`` unique constraint, the re-parented portfolio
  names). NAV values, invested amounts and ``portfolio_id`` are untouched, so
  firm-wide AUM / invested / portfolio-count are invariant — which ``verify`` asserts.
* **Engine-agnostic** — uses ORM/Core expressions only (no Postgres-only SQL), so the
  CI fixture can run the real migration on SQLite.

The auth alias (``resolve_login_target``) lets a retired username keep working
during the grace period: login resolves ``merged_into`` and issues the JWT for the
survivor, so the retired login lands on the unified account.
"""

from __future__ import annotations

import datetime as _dt
from collections import defaultdict
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Iterable

from sqlalchemy import and_, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.models.cash_flow import CashFlow
from backend.models.client import Client
from backend.models.drawdown import DrawdownSeries
from backend.models.holding import Holding
from backend.models.merge_audit import MergeAudit
from backend.models.nav_series import NavSeries
from backend.models.portfolio import Portfolio
from backend.models.risk_metric import RiskMetric
from backend.models.transaction import Transaction

# Every per-client data table re-parented during a merge (besides cpp_portfolios,
# which is handled specially because of its (client_id, portfolio_name) unique key).
_DATA_MODELS: tuple[Any, ...] = (
    NavSeries,
    Transaction,
    Holding,
    RiskMetric,
    DrawdownSeries,
    CashFlow,
)

_Q2 = Decimal("0.01")


class MergeInvariantError(RuntimeError):
    """Raised when a post-merge invariant fails — the caller must roll back."""


# ──────────────────────────────────────────────────────────────────────────────
# Pure helpers
# ──────────────────────────────────────────────────────────────────────────────


def _login_key(last_login: _dt.datetime | None) -> _dt.datetime:
    """Normalise a (possibly tz-aware / NULL) last_login into a comparable naive dt.

    A client that never logged in sorts below any that has (datetime.min).
    """
    if last_login is None:
        return _dt.datetime.min
    if last_login.tzinfo is not None:
        return last_login.astimezone(_dt.timezone.utc).replace(tzinfo=None)
    return last_login


def pick_survivor(members: Iterable[Any]) -> Any:
    """Pick the survivor from a same-name group of clients. Pure.

    Rule (most → least significant): an active account beats a disabled one (you
    can't log into a disabled survivor); then the most recently logged-in client
    wins; clients that have logged in always beat clients that never did; ties
    (including an all-never-logged-in group) break to the lowest ``id``. The
    survivor is the live code the person already signs in with, deterministically.
    """
    members = list(members)
    if not members:
        raise ValueError("pick_survivor() requires at least one member")
    # max over (is_active, has_login, login_time, -id): active beats disabled;
    # a real login beats none; later login beats earlier; tie → lowest id (max -id).
    return max(
        members,
        key=lambda m: (
            bool(getattr(m, "is_active", True)),
            getattr(m, "last_login", None) is not None,
            _login_key(getattr(m, "last_login", None)),
            -int(m.id),
        ),
    )


def _unique_portfolio_name(p: Portfolio) -> str:
    """A portfolio name guaranteed unique under any survivor.

    Every portfolio currently defaults to "PMS Equity", which would collide on the
    ``(client_id, portfolio_name)`` unique constraint once two of them share an
    owner. ``client_code`` is globally unique (uq_cpp_portfolios_client_code), so a
    code-tagged name is collision-proof; fall back to the (unique) portfolio id when
    a code is somehow absent. Idempotent — never double-tags.
    """
    tag = p.client_code or f"#{p.id}"
    base = (p.portfolio_name or "PMS Equity").strip()
    suffix = f"({tag})"
    if base.endswith(suffix):
        return base
    return f"{base} {suffix}"


def _q2(value: Any) -> Decimal:
    """Quantise any numeric to 2dp Decimal for stable invariant comparisons."""
    if value is None:
        return Decimal("0").quantize(_Q2)
    return Decimal(str(value)).quantize(_Q2, rounding=ROUND_HALF_UP)


# ──────────────────────────────────────────────────────────────────────────────
# Baseline + invariants
# ──────────────────────────────────────────────────────────────────────────────


async def _aum_snapshot(db: AsyncSession) -> dict[str, Any]:
    """Firm-wide totals from the latest NAV row of every portfolio.

    Matches scripts/preflight_merge_report.sql §9 (all portfolios, no closed
    filter): summing the latest nav_value / invested_amount / current_value.

    Picks EXACTLY ONE row per portfolio — the latest nav_date, tie-broken by the
    highest id — so the sum is well-defined and equals the preflight's DISTINCT ON
    even in the (constraint-permitted) corrupt case where a portfolio has two NAV
    rows on its max date under different client_ids. Portable: no DISTINCT ON /
    window functions, so the CI fixture runs it on SQLite.
    """
    max_date = (
        select(
            NavSeries.portfolio_id.label("pid"),
            func.max(NavSeries.nav_date).label("md"),
        )
        .group_by(NavSeries.portfolio_id)
        .subquery()
    )
    latest_ids = (
        select(func.max(NavSeries.id).label("nid"))
        .select_from(NavSeries)
        .join(
            max_date,
            and_(
                NavSeries.portfolio_id == max_date.c.pid,
                NavSeries.nav_date == max_date.c.md,
            ),
        )
        .group_by(NavSeries.portfolio_id)
        .subquery()
    )
    stmt = select(
        func.count().label("portfolios_with_nav"),
        func.coalesce(func.sum(NavSeries.nav_value), 0).label("total_aum"),
        func.coalesce(func.sum(NavSeries.invested_amount), 0).label("total_invested"),
        func.coalesce(func.sum(NavSeries.current_value), 0).label("total_current"),
    ).where(NavSeries.id.in_(select(latest_ids.c.nid)))
    row = (await db.execute(stmt)).one()
    return {
        "portfolios_with_nav": int(row.portfolios_with_nav or 0),
        "total_aum": _q2(row.total_aum),
        "total_invested": _q2(row.total_invested),
        "total_current_value": _q2(row.total_current),
    }


async def capture_baseline(db: AsyncSession) -> dict[str, Any]:
    """Snapshot the invariants to assert before/after the merge.

    Captured BEFORE any write. ``verify_merge_invariants`` re-computes the same
    figures afterwards and asserts equality.
    """
    snap = await _aum_snapshot(db)
    portfolio_count = (await db.execute(select(func.count()).select_from(Portfolio))).scalar() or 0
    return {**snap, "portfolio_count": int(portfolio_count)}


async def verify_merge_invariants(db: AsyncSession, baseline: dict[str, Any]) -> dict[str, Any]:
    """Assert every post-merge invariant. Raises MergeInvariantError on any failure.

    Run AFTER the merge writes are flushed but BEFORE commit (reconcile-before-commit).
    Reads via column-level selects / aggregates so it reflects DB truth and never
    trusts a possibly-stale ORM identity-map object.
    """
    failures: list[str] = []

    # 1–3. Firm-wide totals + portfolio count are invariant under the merge.
    after = await _aum_snapshot(db)
    after_pf_count = (await db.execute(select(func.count()).select_from(Portfolio))).scalar() or 0

    if after["total_aum"] != baseline["total_aum"]:
        failures.append(f"AUM changed: {baseline['total_aum']} -> {after['total_aum']}")
    if after["total_invested"] != baseline["total_invested"]:
        failures.append(
            f"invested changed: {baseline['total_invested']} -> {after['total_invested']}"
        )
    if after["total_current_value"] != baseline["total_current_value"]:
        failures.append(
            f"current_value changed: {baseline['total_current_value']} -> {after['total_current_value']}"
        )
    if int(after_pf_count) != int(baseline["portfolio_count"]):
        failures.append(
            f"portfolio count changed: {baseline['portfolio_count']} -> {after_pf_count}"
        )

    # 4. Cross-table ownership: every data row's client_id == its portfolio's owner,
    #    AND no data row dangles off a missing portfolio (a LEFT JOIN catches the
    #    orphan an INNER JOIN would silently drop).
    ownership: dict[str, int] = {}
    dangling: dict[str, int] = {}
    portfolio_ids = select(Portfolio.id)
    for model in _DATA_MODELS:
        n = (await db.execute(
            select(func.count())
            .select_from(model)
            .join(Portfolio, Portfolio.id == model.portfolio_id)
            .where(model.client_id != Portfolio.client_id)
        )).scalar() or 0
        ownership[model.__tablename__] = int(n)
        if n:
            failures.append(f"{model.__tablename__}: {n} row(s) with client_id != portfolio owner")

        d = (await db.execute(
            select(func.count())
            .select_from(model)
            .where(model.portfolio_id.notin_(portfolio_ids))
        )).scalar() or 0
        dangling[model.__tablename__] = int(d)
        if d:
            failures.append(f"{model.__tablename__}: {d} row(s) reference a missing portfolio")

    # 5. Orphans: no live portfolio or data row may be owned by a retired client.
    orphans: dict[str, int] = {}
    retired_ids = select(Client.id).where(Client.merged_into.isnot(None))
    for model in (Portfolio, *_DATA_MODELS):
        n = (await db.execute(
            select(func.count())
            .select_from(model)
            .where(model.client_id.in_(retired_ids))
        )).scalar() or 0
        orphans[model.__tablename__] = int(n)
        if n:
            failures.append(f"{model.__tablename__}: {n} row(s) still owned by a retired client")

    # 6. No merge chains: a survivor must never itself be retired (A->B->C). This is
    #    durable. Name-grouping consistency is asserted at MERGE time instead (see
    #    merge_clients_by_name) — it is NOT re-checked here, because a survivor's
    #    name can legitimately be edited after a merge, which must not block future
    #    runs. Column-level selects → DB truth (never a stale ORM attribute).
    id_to_merged = dict((await db.execute(select(Client.id, Client.merged_into))).all())
    retired_rows = (await db.execute(
        select(Client.id, Client.merged_into).where(Client.merged_into.isnot(None))
    )).all()
    chained = sum(1 for _rid, sid in retired_rows if id_to_merged.get(sid) is not None)
    if chained:
        failures.append(f"{chained} merge chain(s) detected (survivor is itself retired)")

    report = {
        "after": after,
        "portfolio_count": int(after_pf_count),
        "ownership_mismatches": ownership,
        "dangling_portfolio_refs": dangling,
        "orphans": orphans,
        "retired_count": len(retired_rows),
        "chained": chained,
        "ok": not failures,
    }
    if failures:
        raise MergeInvariantError("; ".join(failures))
    return report


# ──────────────────────────────────────────────────────────────────────────────
# The merge
# ──────────────────────────────────────────────────────────────────────────────


async def _count_owned(db: AsyncSession, model: Any, client_id: int) -> int:
    return int((await db.execute(
        select(func.count()).select_from(model).where(model.client_id == client_id)
    )).scalar() or 0)


async def merge_clients_by_name(db: AsyncSession, dry_run: bool = True) -> dict[str, Any]:
    """Group non-admin/non-deleted/un-merged clients by exact name and fold each
    multi-code group onto its survivor.

    When ``dry_run`` (the default) is True this is **read-only**: it computes the
    full plan + row counts and writes nothing. When False it performs every write
    through ``db`` and flushes, but does NOT commit — the caller runs
    ``verify_merge_invariants`` and commits only on success.

    Returns a structured report (groups, survivors, retired ids, per-table row
    counts, totals) suitable for printing in the CLI dry-run.
    """
    clients = list((await db.execute(
        select(Client).where(
            Client.is_admin.is_(False),
            Client.is_deleted.is_(False),
            Client.merged_into.is_(None),
        )
    )).scalars().all())

    groups: dict[str, list[Client]] = defaultdict(list)
    for c in clients:
        groups[c.name].append(c)

    report_groups: list[dict[str, Any]] = []
    total_retired = 0
    total_rows_reparented = 0
    total_portfolios_reparented = 0

    # Deterministic group order for stable reports/output.
    for name in sorted(groups):
        members = groups[name]
        if len(members) < 2:
            continue
        survivor = pick_survivor(members)
        retired = sorted(
            (m for m in members if m.id != survivor.id), key=lambda m: m.id
        )

        # Name-grouping is correct by construction (we grouped by exact name), but
        # assert it defensively at the point it must hold — guards against ever
        # folding differently-named clients together.
        bad = [m for m in members if m.name != survivor.name]
        if bad:
            raise MergeInvariantError(
                f"name-group {name!r} contains mismatched names: "
                f"{sorted({m.name for m in bad})}"
            )

        grp: dict[str, Any] = {
            "name": name,
            "survivor": {
                "id": survivor.id,
                "client_code": survivor.client_code,
                "username": survivor.username,
            },
            "retired": [],
        }

        for r in retired:
            # Portfolios — re-parent + rename to keep the unique name constraint.
            pfs = list((await db.execute(
                select(Portfolio).where(Portfolio.client_id == r.id)
            )).scalars().all())
            for p in pfs:
                if not dry_run:
                    await db.execute(
                        update(Portfolio)
                        .where(Portfolio.id == p.id)
                        .values(client_id=survivor.id, portfolio_name=_unique_portfolio_name(p))
                        .execution_options(synchronize_session=False)
                    )

            # Data tables — re-parent client_id (portfolio_id unchanged → no
            # unique collisions on the data tables).
            per_table: dict[str, int] = {}
            for model in _DATA_MODELS:
                n = await _count_owned(db, model, r.id)
                per_table[model.__tablename__] = n
                if not dry_run and n:
                    await db.execute(
                        update(model)
                        .where(model.client_id == r.id)
                        .values(client_id=survivor.id)
                        .execution_options(synchronize_session=False)
                    )

            if not dry_run:
                # Soft-retire (keep is_active for alias grace) + audit.
                await db.execute(
                    update(Client)
                    .where(Client.id == r.id)
                    .values(merged_into=survivor.id)
                    .execution_options(synchronize_session=False)
                )
                db.add(MergeAudit(
                    survivor_id=survivor.id,
                    retired_id=r.id,
                    retired_code=r.client_code,
                    retired_username=r.username,
                    name=r.name,
                ))

            rows_moved = sum(per_table.values())
            total_retired += 1
            total_rows_reparented += rows_moved
            total_portfolios_reparented += len(pfs)
            grp["retired"].append({
                "id": r.id,
                "client_code": r.client_code,
                "username": r.username,
                "portfolios": len(pfs),
                "reparented": per_table,
                "rows_reparented": rows_moved,
            })

        report_groups.append(grp)

    if not dry_run:
        # Make audit inserts + updates visible to verify (still uncommitted).
        await db.flush()

    return {
        "dry_run": dry_run,
        "groups": report_groups,
        "totals": {
            "people": len(groups),
            "single_code_people": sum(1 for m in groups.values() if len(m) == 1),
            "multi_code_groups": len(report_groups),
            "codes_retired": total_retired,
            "portfolios_reparented": total_portfolios_reparented,
            "rows_reparented": total_rows_reparented,
        },
    }


# ──────────────────────────────────────────────────────────────────────────────
# Auth alias
# ──────────────────────────────────────────────────────────────────────────────


_MAX_MERGE_HOPS = 8


async def resolve_login_target(db: AsyncSession, client: Client) -> Client | None:
    """Resolve a (possibly retired) login to the account it should land on.

    * Un-merged login → returns ``client`` unchanged.
    * Retired login → follows ``merged_into`` to the terminal survivor (chasing a
      multi-round chain A->B->C, with a cycle/length guard) and returns it. The
      retired username thus keeps working during the grace period and lands on the
      unified account; login issues the JWT for the returned client.
    * Retired login whose unified account is unavailable (missing / inactive /
      deleted) → returns ``None``. The caller must DENY the login rather than
      strand the user on the now-empty retired account or silently grant access to
      a disabled unified account.

    The survivor is loaded with its portfolios so callers can read
    ``client.portfolios`` in the async context without a lazy-load IO error.
    """
    if getattr(client, "merged_into", None) is None:
        return client

    current = client
    seen: set[int] = {client.id}
    for _ in range(_MAX_MERGE_HOPS):
        survivor_id = current.merged_into
        if survivor_id is None:
            # Reached a terminal account — it must be usable to land on.
            if not current.is_active or current.is_deleted:
                return None
            return current
        if survivor_id in seen:
            return None  # cycle — refuse to loop
        seen.add(survivor_id)
        current = (await db.execute(
            select(Client)
            .options(selectinload(Client.portfolios))
            .where(Client.id == survivor_id)
        )).scalar_one_or_none()
        if current is None:
            return None
    return None  # chain too long — refuse rather than guess
