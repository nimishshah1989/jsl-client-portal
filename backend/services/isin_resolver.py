"""
ISIN → NSE ticker resolution service.

ISINs are 12-character identifiers assigned at instrument issuance.
They are stable across renames, mergers, and exchange changes, unlike
NSE ticker symbols which can change (e.g. HDFC Bank → HDFCBANK,
PVR → PVRINOX, Adani Transmission → ADANIENSOL).

The backoffice records instruments using script names / company names,
NOT NSE tickers. This module resolves the ISIN (always present in the
21-col transaction format) to the canonical NSE ticker for price fetching.

Resolution priority (fastest to slowest):
  1. Module-level cache (populated at startup from DB, zero I/O)
  2. Yahoo Finance search API (1 HTTP call per unknown ISIN, result cached)

The cache lives for the process lifetime. ISINs resolved via Yahoo Finance
are logged so they can be added to txn_parser._SYMBOL_OVERRIDES for
compile-time resolution in future.

Usage:
    await seed_cache_from_db(db)             # call once at startup
    ticker = get_cached_ticker("INF769K...")  # sync, from cache only
    ticker = await resolve(isin)             # async, fetches if not cached
    tickers = await resolve_batch(isins)     # batch, minimises API calls
"""

from __future__ import annotations

import logging
import re

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# Lazy import to avoid circular-import risk at module load time.
# _SYMBOL_OVERRIDES is only needed inside functions, not at import time.
def _get_overrides() -> dict[str, str]:
    from backend.services.txn_parser import _SYMBOL_OVERRIDES  # noqa: PLC0415
    return _SYMBOL_OVERRIDES


logger = logging.getLogger(__name__)

# ISIN → yfinance-compatible ticker (e.g. "ATHERENERG.NS")
# None means "tried Yahoo Finance, confirmed not found on NSE/BSE"
_CACHE: dict[str, str | None] = {}

# Whether the DB seed has run for this process
_SEEDED: bool = False

# NSE ticker pattern: uppercase letters/digits, optionally with &
# Max 12 chars covers all real NSE tickers (most are 5-10 chars)
_NSE_TICKER_RE = re.compile(r"^[A-Z0-9&]{2,12}$")

_YF_SEARCH_URL = "https://query1.finance.yahoo.com/v1/finance/search"
_YF_SEARCH_TIMEOUT = 10  # seconds


# ── Cache seeding ─────────────────────────────────────────────────────────────


async def seed_cache_from_db(db: AsyncSession) -> int:
    """
    Pre-populate the ISIN→ticker cache from cpp_transactions.

    For each ISIN, finds all associated symbols in the DB and picks the one
    that looks most like a real NSE ticker (shortest AND matches ticker pattern).
    Long company-name concatenations (ATHERENERGYLIMITED, ZOMATOLIMITED, etc.)
    are ignored in favour of the shorter canonical ticker if both exist for the
    same ISIN.

    Returns the number of ISINs successfully seeded.
    No-ops on subsequent calls within the same process (cache is already warm).
    """
    global _SEEDED
    if _SEEDED:
        return 0  # already seeded this process — avoid redundant DB query
    result = await db.execute(
        text("""
            SELECT isin, symbol
            FROM cpp_transactions
            WHERE isin IS NOT NULL
              AND isin != ''
              AND length(isin) = 12
            ORDER BY isin, length(symbol) ASC
        """)
    )

    # Group all symbols per ISIN, ordered shortest-first
    by_isin: dict[str, list[str]] = {}
    for row in result.fetchall():
        isin, sym = row[0].strip(), row[1].strip()
        if isin:
            by_isin.setdefault(isin, []).append(sym)

    seeded = 0
    for isin, symbols in by_isin.items():
        if isin in _CACHE:
            continue  # already resolved (e.g. from a previous price update)
        # Pick the first symbol that matches the NSE ticker pattern.
        # Apply overrides BEFORE the regex check so long parsed symbols like
        # "MIRAESMALLCAP" (13 chars) can still seed via their short canonical
        # ticker ("SMALLCAP") instead of falling through to Yahoo Finance search.
        overrides = _get_overrides()
        for sym in symbols:
            canonical = overrides.get(sym, sym)
            if _NSE_TICKER_RE.match(canonical):
                _CACHE[isin] = f"{canonical}.NS"
                seeded += 1
                break
        # If no symbol matched the pattern, the ISIN will be resolved via
        # Yahoo Finance search on demand when encountered in resolve()

    _SEEDED = True
    logger.info(
        "ISIN cache seeded: %d ISINs from DB (%d total in DB, %d pending Yahoo Finance)",
        seeded,
        len(by_isin),
        len(by_isin) - seeded,
    )
    return seeded


# ── Resolution ────────────────────────────────────────────────────────────────


def get_cached_ticker(isin: str) -> str | None:
    """
    Synchronous cache-only lookup.  Returns None if not cached yet.
    Use for hot paths where network I/O is not acceptable.
    """
    return _CACHE.get(isin)


async def resolve(isin: str) -> str | None:
    """
    Resolve an ISIN to a yfinance-compatible NSE ticker.

    Checks the in-process cache first. On a miss, queries Yahoo Finance's
    search endpoint with the ISIN, which returns exchange-qualified tickers
    (e.g. "MASMC250.NS"). NSE (.NS) is preferred over BSE (.BO).

    Returns e.g. "MASMC250.NS" or None if the instrument is not listed.
    The result (including None) is cached to prevent repeated API calls.
    """
    if not isin or len(isin) != 12:
        return None
    if isin in _CACHE:
        return _CACHE[isin]

    ticker = await _yahoo_search(isin)
    _CACHE[isin] = ticker
    if ticker:
        logger.info("ISIN resolved via Yahoo Finance: %s → %s", isin, ticker)
    else:
        logger.debug("ISIN not found on NSE/BSE: %s", isin)
    return ticker


async def resolve_batch(isins: list[str]) -> dict[str, str]:
    """
    Resolve multiple ISINs, hitting Yahoo Finance only for those not cached.

    Returns {isin: ticker} for successfully resolved ISINs only (missing
    ones are omitted — caller can treat absence as unresolvable).
    """
    result: dict[str, str] = {}
    to_fetch: list[str] = []

    for isin in isins:
        if not isin or len(isin) != 12:
            continue
        if isin in _CACHE:
            if _CACHE[isin] is not None:
                result[isin] = _CACHE[isin]  # type: ignore[assignment]
        else:
            to_fetch.append(isin)

    if to_fetch:
        async with httpx.AsyncClient(
            timeout=_YF_SEARCH_TIMEOUT,
            follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 (compatible; portfolio-tracker/1.0)"},
        ) as client:
            for isin in to_fetch:
                ticker = await _yahoo_search(isin, client=client)
                _CACHE[isin] = ticker
                if ticker:
                    result[isin] = ticker
                    logger.info("ISIN resolved: %s → %s", isin, ticker)
                else:
                    logger.debug("ISIN unresolvable: %s", isin)

    return result


# ── Helpers ───────────────────────────────────────────────────────────────────


def isin_to_symbol(ticker: str | None) -> str | None:
    """
    Strip the exchange suffix from a yfinance ticker to get the plain symbol.

    "ATHERENERG.NS" → "ATHERENERG"
    "MASMC250.BO"   → "MASMC250"
    None            → None
    """
    if ticker is None:
        return None
    return ticker.rsplit(".", 1)[0]


async def _yahoo_search(
    isin: str,
    client: httpx.AsyncClient | None = None,
) -> str | None:
    """Call Yahoo Finance search API with an ISIN. Returns NSE (.NS) ticker or None."""
    try:
        params = {
            "q": isin,
            "quotesCount": 5,
            "newsCount": 0,
            "enableFuzzyQuery": "false",
        }
        headers = {"User-Agent": "Mozilla/5.0 (compatible; portfolio-tracker/1.0)"}
        if client:
            resp = await client.get(_YF_SEARCH_URL, params=params, headers=headers)
        else:
            async with httpx.AsyncClient(
                timeout=_YF_SEARCH_TIMEOUT,
                follow_redirects=True,
            ) as c:
                resp = await c.get(_YF_SEARCH_URL, params=params, headers=headers)

        if resp.status_code != 200:
            logger.debug("Yahoo Finance search returned %d for ISIN %s", resp.status_code, isin)
            return None

        quotes = resp.json().get("quotes", [])
        # Prefer NSE (.NS), fall back to BSE (.BO)
        ns_ticker: str | None = None
        bo_ticker: str | None = None
        for q in quotes:
            sym = q.get("symbol", "")
            if sym.endswith(".NS") and ns_ticker is None:
                ns_ticker = sym
            elif sym.endswith(".BO") and bo_ticker is None:
                bo_ticker = sym

        chosen = ns_ticker or bo_ticker
        if chosen:
            # Apply symbol overrides: Yahoo Finance may return stale tickers for
            # merged/renamed companies (e.g. "LTI.NS" instead of "LTIM.NS").
            overrides = _get_overrides()
            plain = chosen.rsplit(".", 1)[0]
            canonical = overrides.get(plain, plain)
            exchange = chosen.rsplit(".", 1)[1]
            chosen = f"{canonical}.{exchange}"
        return chosen

    except Exception as exc:
        logger.debug("Yahoo Finance search failed for %s: %s", isin, exc)
        return None
