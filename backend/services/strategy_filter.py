"""Strategy scoping for the admin aggregate views.

Single helper that turns a strategy selection (COMBINED / LEADERS / PASSIVE /
IND11) into the SQL fragments that scope an aggregate query to that strategy's
*live* portfolios. Live always excludes closed accounts (is_closed = true), so
the firm totals and per-strategy views never count archived accounts.

The join is on ``portfolio_id`` (not client_id) so it stays correct once a
client owns several portfolios across strategies.
"""

from __future__ import annotations

STRATEGY_COMBINED = "COMBINED"
VALID_STRATEGIES = (STRATEGY_COMBINED, "LEADERS", "PASSIVE", "IND11")


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
