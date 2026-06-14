"""Admin dashboard analytics — firm-wide aggregates for the admin landing page.

Aggregation is **per-portfolio**, not ``DISTINCT ON (client_id)``. Once a person
owns several portfolios (after the PR7 unified-login merge re-parents their
sleeves onto one survivor client), a per-client "latest row" only sees one sleeve
and undercounts that client's StatCards. Selecting each portfolio's own latest
row and summing fixes this — it mirrors
:func:`aggregate_service._fetch_bucket_aum`'s per-portfolio-latest snapshot and is
the same AUM truth the merge invariant uses.

Returns/ratios (CAGR, Sharpe, max DD) are AUM-weighted across portfolios — only ₹
quantities are additive (L-009). The "top performers" lists are then rolled up to
one row per person so the admin UI (which keys on ``client_id``) shows each client
once with their combined AUM, even when they hold several sleeves.

All SQL is engine-portable (no ``DISTINCT ON`` / window functions) so the CI
fixture exercises the real query on SQLite (L-010/L-011).
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.services.strategy_filter import (
    active_clause,
    active_cutoff,
    active_params,
    portfolio_clause,
    strategy_params,
)


async def compute_dashboard_analytics(
    db: AsyncSession,
    strategy: str = "COMBINED",
    include_inactive: bool = False,
) -> dict[str, Any]:
    """Aggregate analytics for the admin dashboard, scoped to a strategy.

    Strategy is COMBINED / LEADERS / PASSIVE / IND11; closed accounts are always
    excluded. Active-only by default (stale/dormant sleeves dropped); the admin
    can opt back in via ``include_inactive``.

    Returns:
        total_aum / total_invested / total_profit(_pct): Σ over each portfolio's
            OWN latest NAV (per-portfolio, so a unified client's sleeves all count).
        total_clients: number of distinct people with a live portfolio.
        blended_cagr / blended_sharpe / avg_max_drawdown: AUM-weighted across
            portfolios.
        total_cash / total_cash_pct: cash (ETF + ledger + bank, falling back to
            Liquidity%) summed across portfolios.
        top_performers / bottom_performers / top_by_nav / top_by_invested:
            one row per person (sleeves rolled up).
        data_as_of: latest NAV date in scope.
        recent_uploads: last 5 upload-log rows.
    """
    cutoff = None if include_inactive else await active_cutoff(db)
    params = {**strategy_params(strategy), **active_params(include_inactive, cutoff)}

    total_clients = await _fetch_client_count(db, strategy, include_inactive, cutoff, params)
    nav_rows = await _fetch_latest_nav_rows(db, strategy, include_inactive, cutoff, params)
    risk_rows = await _fetch_latest_risk_rows(db, strategy, include_inactive, cutoff, params)

    # ── Per-portfolio ₹ aggregation (the fix: sum every sleeve, not one per client)
    aum_by_portfolio: dict[int, float] = {}
    invested_by_portfolio: dict[int, float] = {}
    total_aum = 0.0
    total_invested = 0.0
    total_cash = 0.0
    data_as_of = None

    for row in nav_rows:
        nav_val = float(row.nav_value or 0)
        aum_by_portfolio[row.portfolio_id] = nav_val
        invested_by_portfolio[row.portfolio_id] = float(row.invested_amount or 0)
        total_aum += nav_val
        total_invested += float(row.invested_amount or 0)
        total_cash += _row_cash(row, nav_val)
        # Postgres returns nav_date as a date; SQLite (raw text() SELECT) as a
        # string — normalise so comparison + isoformat work on both (L-009).
        nav_date = _as_date(row.nav_date)
        if nav_date and (data_as_of is None or nav_date > data_as_of):
            data_as_of = nav_date

    total_cash_pct = (total_cash / total_aum * 100) if total_aum > 0 else 0.0
    total_profit = total_aum - total_invested
    total_profit_pct = (
        (total_aum / total_invested - 1) * 100 if total_invested > 0 else 0.0
    )

    # ── Blended (AUM-weighted) firm metrics + per-person performer rollup
    blended, client_metrics = _aggregate_risk(
        risk_rows, aum_by_portfolio, invested_by_portfolio
    )

    by_cagr = sorted(client_metrics, key=lambda x: x["cagr"], reverse=True)
    by_aum = sorted(client_metrics, key=lambda x: x["aum"], reverse=True)
    by_invested = sorted(client_metrics, key=lambda x: x["invested"], reverse=True)

    upload_history = await _fetch_upload_history(db)

    return {
        "total_aum": round(total_aum, 2),
        "total_invested": round(total_invested, 2),
        "total_profit": round(total_profit, 2),
        "total_profit_pct": round(total_profit_pct, 2),
        "total_clients": total_clients,
        "blended_cagr": round(blended["cagr"], 2),
        "blended_sharpe": round(blended["sharpe"], 2),
        "total_cash": round(total_cash, 2),
        "total_cash_pct": round(total_cash_pct, 2),
        "avg_max_drawdown": round(blended["max_dd"], 2),
        "top_performers": by_cagr[:5],
        "top_by_nav": by_aum[:5],
        "top_by_invested": by_invested[:5],
        "bottom_performers": by_cagr[-5:] if len(by_cagr) > 5 else [],
        "data_as_of": data_as_of.isoformat() if data_as_of else None,
        "recent_uploads": upload_history,
    }


# ── Private helpers ──────────────────────────────────────────────────────


def _as_date(value: Any) -> dt.date | None:
    """Normalise a NAV date to ``dt.date`` (Postgres → date, SQLite → ISO str)."""
    if value is None or isinstance(value, dt.date):
        return value
    return dt.date.fromisoformat(str(value)[:10])


def _row_cash(row: Any, nav_val: float) -> float:
    """True cash for a NAV row = ETF + ledger cash + bank; fall back to Liquidity%."""
    client_cash = (
        float(row.etf_value or 0)
        + float(row.cash_value or 0)
        + float(row.bank_balance or 0)
    )
    if client_cash > 0:
        return client_cash
    if row.cash_pct and nav_val > 0:
        return nav_val * float(row.cash_pct) / 100
    return 0.0


async def _fetch_client_count(
    db: AsyncSession, strategy: str, include_inactive: bool, cutoff, params: dict,
) -> int:
    """Number of distinct people (clients) with a live portfolio in this strategy.

    Counts clients, not portfolios, so a unified client with several sleeves is
    one person. cpp_portfolios is aliased ``pstrat`` (its id IS the portfolio id),
    so the recency filter keys off ``pstrat.id``.
    """
    active_pstrat = (
        ""
        if (include_inactive or cutoff is None)
        else " AND pstrat.id IN (SELECT portfolio_id FROM cpp_nav_series "
        "GROUP BY portfolio_id HAVING MAX(nav_date) >= :active_cutoff)"
    )
    sql = (
        "SELECT COUNT(DISTINCT c.id) FROM cpp_clients c "
        "JOIN cpp_portfolios pstrat ON pstrat.client_id = c.id "
        "WHERE c.is_active = true AND c.is_admin = false "
        "AND pstrat.is_closed = false"
    )
    if strategy_params(strategy):
        sql += " AND pstrat.strategy = :strategy"
    sql += active_pstrat
    return (await db.execute(text(sql), params)).scalar() or 0


async def _fetch_latest_nav_rows(
    db: AsyncSession, strategy: str, include_inactive: bool, cutoff, params: dict,
) -> list[Any]:
    """Each in-scope portfolio's own latest NAV row (per-portfolio, not per-client).

    Portable equivalent of ``DISTINCT ON (portfolio_id) ... ORDER BY nav_date DESC``:
    MAX(nav_date) per portfolio, then MAX(id) as a deterministic tiebreak.
    """
    join, where = portfolio_clause(strategy, alias="n")
    active = active_clause(include_inactive, cutoff, alias="n")
    result = await db.execute(text(f"""
        WITH md AS (
            SELECT n.portfolio_id AS pid, MAX(n.nav_date) AS mxd
            FROM cpp_nav_series n
            JOIN cpp_clients c ON c.id = n.client_id
            {join}
            WHERE c.is_active = true AND c.is_admin = false
              {where}{active}
            GROUP BY n.portfolio_id
        ),
        latest_ids AS (
            SELECT MAX(n2.id) AS nid
            FROM cpp_nav_series n2
            JOIN md ON md.pid = n2.portfolio_id AND n2.nav_date = md.mxd
            GROUP BY n2.portfolio_id
        )
        SELECT
            n.client_id, n.portfolio_id, c.name, c.client_code,
            n.nav_value, n.invested_amount, n.nav_date,
            COALESCE(n.etf_value, 0) AS etf_value,
            COALESCE(n.cash_value, 0) AS cash_value,
            COALESCE(n.bank_balance, 0) AS bank_balance,
            n.cash_pct
        FROM cpp_nav_series n
        JOIN cpp_clients c ON c.id = n.client_id
        WHERE n.id IN (SELECT nid FROM latest_ids)
    """), params)
    return result.fetchall()


async def _fetch_latest_risk_rows(
    db: AsyncSession, strategy: str, include_inactive: bool, cutoff, params: dict,
) -> list[Any]:
    """Each in-scope portfolio's own latest risk-metrics row (per-portfolio)."""
    join, where = portfolio_clause(strategy, alias="r")
    active = active_clause(include_inactive, cutoff, alias="r")
    result = await db.execute(text(f"""
        WITH md AS (
            SELECT r.portfolio_id AS pid, MAX(r.computed_date) AS mxd
            FROM cpp_risk_metrics r
            JOIN cpp_clients c ON c.id = r.client_id
            {join}
            WHERE c.is_active = true AND c.is_admin = false
              {where}{active}
            GROUP BY r.portfolio_id
        ),
        latest_ids AS (
            SELECT MAX(r2.id) AS rid
            FROM cpp_risk_metrics r2
            JOIN md ON md.pid = r2.portfolio_id AND r2.computed_date = md.mxd
            GROUP BY r2.portfolio_id
        )
        SELECT
            r.client_id, r.portfolio_id, c.name, c.client_code,
            r.cagr, r.max_drawdown, r.sharpe_ratio, r.xirr
        FROM cpp_risk_metrics r
        JOIN cpp_clients c ON c.id = r.client_id
        WHERE r.id IN (SELECT rid FROM latest_ids)
    """), params)
    return result.fetchall()


def _aggregate_risk(
    risk_rows: list[Any],
    aum_by_portfolio: dict[int, float],
    invested_by_portfolio: dict[int, float],
) -> tuple[dict[str, float], list[dict[str, Any]]]:
    """AUM-weight per-portfolio risk into firm blended metrics + per-person rows.

    Firm blended metrics weight every portfolio by its own latest AUM. The
    performer rows roll each person's sleeves into a single entry (sum AUM /
    invested; AUM-weight the ratios) so the admin UI shows one row per client.
    """
    weighted_cagr = weighted_dd = weighted_sharpe = total_weight = 0.0
    per_client: dict[int, dict[str, Any]] = {}

    for row in risk_rows:
        weight = aum_by_portfolio.get(row.portfolio_id, 0.0)
        cagr_val = float(row.cagr or 0)
        dd_val = float(row.max_drawdown or 0)
        sharpe_val = float(row.sharpe_ratio or 0)
        xirr_val = float(row.xirr or 0)

        weighted_cagr += cagr_val * weight
        weighted_dd += dd_val * weight
        weighted_sharpe += sharpe_val * weight
        total_weight += weight

        cm = per_client.setdefault(row.client_id, {
            "client_id": row.client_id,
            "name": row.name,
            "client_code": row.client_code,
            "aum": 0.0,
            "invested": 0.0,
            "_wcagr": 0.0,
            "_wdd": 0.0,
            "_wsharpe": 0.0,
            "_wxirr": 0.0,
            "_w": 0.0,
        })
        cm["aum"] += weight
        cm["invested"] += invested_by_portfolio.get(row.portfolio_id, 0.0)
        cm["_wcagr"] += cagr_val * weight
        cm["_wdd"] += dd_val * weight
        cm["_wsharpe"] += sharpe_val * weight
        cm["_wxirr"] += xirr_val * weight
        cm["_w"] += weight

    blended = {
        "cagr": weighted_cagr / total_weight if total_weight > 0 else 0.0,
        "max_dd": weighted_dd / total_weight if total_weight > 0 else 0.0,
        "sharpe": weighted_sharpe / total_weight if total_weight > 0 else 0.0,
    }

    client_metrics: list[dict[str, Any]] = []
    for cm in per_client.values():
        w = cm["_w"]
        client_metrics.append({
            "client_id": cm["client_id"],
            "name": cm["name"],
            "client_code": cm["client_code"],
            "cagr": round(cm["_wcagr"] / w, 2) if w > 0 else 0.0,
            "max_drawdown": round(cm["_wdd"] / w, 2) if w > 0 else 0.0,
            "sharpe_ratio": round(cm["_wsharpe"] / w, 2) if w > 0 else 0.0,
            "xirr": round(cm["_wxirr"] / w, 2) if w > 0 else 0.0,
            "aum": round(cm["aum"], 2),
            "invested": round(cm["invested"], 2),
        })
    return blended, client_metrics


async def _fetch_upload_history(db: AsyncSession) -> list[dict[str, Any]]:
    """Last 5 upload-log rows for the admin dashboard's recent-activity panel."""
    result = await db.execute(text("""
        SELECT file_type, filename, rows_processed, clients_affected, uploaded_at
        FROM cpp_upload_log
        ORDER BY uploaded_at DESC
        LIMIT 5
    """))
    return [
        {
            "file_type": r.file_type,
            "filename": r.filename,
            "rows_processed": r.rows_processed,
            "clients_affected": r.clients_affected,
            "uploaded_at": r.uploaded_at.isoformat() if r.uploaded_at else None,
        }
        for r in result.fetchall()
    ]
