"""Strategy scoping for the admin aggregate views.

Single helper that turns a strategy selection (COMBINED / LEADERS / PASSIVE /
IND11) into the SQL fragments that scope an aggregate query to that strategy's
*live* portfolios. Live always excludes closed accounts (is_closed = true), so
the firm totals and per-strategy views never count archived accounts.

The join is on ``portfolio_id`` (not client_id) so it stays correct once a
client owns several portfolios across strategies.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

STRATEGY_COMBINED = "COMBINED"
VALID_STRATEGIES = (STRATEGY_COMBINED, "LEADERS", "PASSIVE", "IND11")

# A portfolio is "active" if its latest NAV is within this many days of the firm's
# most recent NAV date. Stale-NAV portfolios (redeemed / dormant accounts that
# dropped out of the daily NAV file) are excluded from live views by default; the
# admin can opt back in via include_inactive. See active_clause / active_cutoff.
ACTIVE_WINDOW_DAYS = 30


def normalize_strategy(strategy: str | None) -> str:
    """Coerce arbitrary input to a valid strategy, defaulting to COMBINED."""
    s = (strategy or STRATEGY_COMBINED).strip().upper()
    return s if s in VALID_STRATEGIES else STRATEGY_COMBINED


def portfolio_clause(strategy: str | None, alias: str = "n") -> tuple[str, str]:
    """Return ``(join_sql, where_sql)`` scoping a query to a strategy's live portfolios.

    ``alias`` is the table alias that carries ``portfolio_id`` (``n`` for
    cpp_nav_series / cpp_risk_metrics, ``h`` for cpp_holdings). Closed portfolios
    are always excluded. The ``:strategy`` bind is referenced only when a single
    strategy is selected — pair this with :func:`strategy_params`.
    """
    strategy = normalize_strategy(strategy)
    join = f"JOIN cpp_portfolios pstrat ON pstrat.id = {alias}.portfolio_id"
    where = "AND pstrat.is_closed = false"
    if strategy != STRATEGY_COMBINED:
        where += " AND pstrat.strategy = :strategy"
    return join, where


def strategy_params(strategy: str | None) -> dict[str, str]:
    """Bind params for :func:`portfolio_clause` — only sets ``strategy`` when a
    single strategy is selected (COMBINED needs no bind)."""
    strategy = normalize_strategy(strategy)
    return {} if strategy == STRATEGY_COMBINED else {"strategy": strategy}


async def active_cutoff(
    db: AsyncSession, window_days: int = ACTIVE_WINDOW_DAYS
) -> dt.date | None:
    """Earliest last-NAV date for a portfolio to still count as 'active' —
    ``window_days`` before the firm's most recent NAV date. ``None`` if there is
    no NAV data at all (then no active filtering is applied)."""
    raw = (await db.execute(text("SELECT MAX(nav_date) FROM cpp_nav_series"))).scalar()
    if raw is None:
        return None
    latest = raw if isinstance(raw, dt.date) else dt.date.fromisoformat(str(raw)[:10])
    return latest - dt.timedelta(days=window_days)


def active_clause(include_inactive: bool, cutoff: dt.date | None, alias: str = "n") -> str:
    """SQL fragment that excludes portfolios whose latest NAV is stale (older than
    the active window). Empty string when ``include_inactive`` is True OR there is
    no cutoff (no NAV data). Pair with :func:`active_params` for the
    ``:active_cutoff`` bind — both gate on the same condition so the bind is
    present exactly when the clause references it.

    ``alias`` is the table alias carrying ``portfolio_id`` (``n`` for
    cpp_nav_series / cpp_risk_metrics, ``h`` for cpp_holdings, ``cf`` for
    cpp_cash_flows). The recency test is always evaluated against cpp_nav_series.
    """
    if include_inactive or cutoff is None:
        return ""
    return (
        f" AND {alias}.portfolio_id IN ("
        "SELECT portfolio_id FROM cpp_nav_series "
        "GROUP BY portfolio_id HAVING MAX(nav_date) >= :active_cutoff)"
    )


def active_params(include_inactive: bool, cutoff: dt.date | None) -> dict[str, dt.date]:
    """Bind params for :func:`active_clause` — sets ``active_cutoff`` exactly when
    the clause is emitted (active-only AND a cutoff date exists)."""
    if include_inactive or cutoff is None:
        return {}
    return {"active_cutoff": cutoff}
