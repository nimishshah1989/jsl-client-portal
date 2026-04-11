"""
Reconciliation commentary generator.

Analyzes mismatch patterns across all clients and generates human-readable
insights: stock splits, systematic cost differences, missing/extra symbols,
overall health, and NAV vs BO total discrepancies.

Extracted from reconciliation_service.py to keep that module under 400 lines.
"""

from __future__ import annotations

from collections import Counter
from decimal import Decimal

_ZERO = Decimal("0")


def generate_commentary(summary) -> list[dict]:
    """
    Analyze mismatch patterns and generate human-readable commentary.

    Detects:
      - Consistent quantity ratios (stock splits/bonuses)
      - Systematic cost differences per symbol
      - Symbols missing/extra across many clients
      - Overall match quality
      - NAV vs BO holding total discrepancies

    Args:
        summary: ReconciliationSummary instance (duck-typed to avoid circular import).

    Returns:
        List of dicts: {type, severity, title, detail, affected_clients}
    """
    insights: list[dict] = []
    all_matches = []
    for c in summary.clients:
        all_matches.extend(c.matches)

    # --- 1. Detect quantity ratio patterns (stock splits/bonuses) ---
    qty_mismatches = [m for m in all_matches if m.status == "QTY_MISMATCH"]
    if qty_mismatches:
        # Group by symbol, check for consistent ratios
        by_symbol: dict[str, list[float]] = {}
        for m in qty_mismatches:
            if m.bo_quantity and m.our_quantity and m.bo_quantity > 0:
                ratio = float(m.our_quantity / m.bo_quantity)
                sym = m.symbol
                if sym not in by_symbol:
                    by_symbol[sym] = []
                by_symbol[sym].append(round(ratio, 1))

        for sym, ratios in by_symbol.items():
            ratio_counts = Counter(ratios)
            dominant_ratio, count = ratio_counts.most_common(1)[0]
            if count >= 3 and dominant_ratio != 1.0:
                # Consistent ratio across multiple clients = likely corporate action
                insights.append({
                    "type": "STOCK_SPLIT",
                    "severity": "high",
                    "title": f"{sym}: Likely {dominant_ratio:.0f}:1 stock split or bonus",
                    "detail": (
                        f"Our system shows {dominant_ratio:.0f}x the quantity vs backoffice "
                        f"across {count} clients. Avg cost matches, confirming this is a "
                        f"corporate action (split/bonus) that the backoffice adjusted but "
                        f"our transaction history hasn't been corrected for."
                    ),
                    "affected_clients": count,
                    "symbol": sym,
                })
            elif count >= 2:
                insights.append({
                    "type": "QTY_PATTERN",
                    "severity": "medium",
                    "title": f"{sym}: Quantity mismatch ({dominant_ratio:.1f}x ratio) across {count} clients",
                    "detail": (
                        f"Consistent {dominant_ratio:.1f}x quantity ratio suggests a "
                        f"corporate action or systematic transaction gap."
                    ),
                    "affected_clients": count,
                    "symbol": sym,
                })

    # --- 2. Detect systematic cost differences per symbol ---
    cost_mismatches = [m for m in all_matches if m.status == "COST_MISMATCH"]
    if cost_mismatches:
        by_symbol_cost: dict[str, list[Decimal]] = {}
        for m in cost_mismatches:
            if m.cost_diff is not None:
                sym = m.symbol
                if sym not in by_symbol_cost:
                    by_symbol_cost[sym] = []
                by_symbol_cost[sym].append(abs(m.cost_diff))

        for sym, diffs in by_symbol_cost.items():
            avg_diff = sum(diffs) / len(diffs)
            if len(diffs) >= 5:
                insights.append({
                    "type": "COST_SYSTEMATIC",
                    "severity": "medium",
                    "title": f"{sym}: Systematic avg cost difference (avg diff: Rs.{avg_diff:.2f})",
                    "detail": (
                        f"Avg cost differs across {len(diffs)} clients by an average of "
                        f"Rs.{avg_diff:.2f}. This is likely due to a corporate action "
                        f"(unit consolidation, bonus) that changed the cost basis in the "
                        f"backoffice but not in our WAC computation."
                    ),
                    "affected_clients": len(diffs),
                    "symbol": sym,
                })

    # --- 3. Symbols extra in ours (sold/removed in backoffice) ---
    extra = [m for m in all_matches if m.status == "EXTRA_IN_OURS"]
    if extra:
        extra_by_sym = Counter(m.symbol for m in extra)
        for sym, count in extra_by_sym.most_common(5):
            if count >= 5:
                insights.append({
                    "type": "EXTRA_SYMBOL",
                    "severity": "medium",
                    "title": f"{sym}: Present in our system but not in backoffice ({count} clients)",
                    "detail": (
                        f"We show {sym} holdings for {count} clients but the backoffice "
                        f"doesn't. This stock was likely sold, transferred out, or removed "
                        f"in a transaction batch we haven't ingested."
                    ),
                    "affected_clients": count,
                    "symbol": sym,
                })

    # --- 4. Symbols missing in ours (new positions in backoffice) ---
    missing = [m for m in all_matches if m.status == "MISSING_IN_OURS"]
    if missing:
        missing_by_sym = Counter(m.symbol for m in missing)
        for sym, count in missing_by_sym.most_common(5):
            if count >= 3:
                insights.append({
                    "type": "MISSING_SYMBOL",
                    "severity": "medium",
                    "title": f"{sym}: Present in backoffice but missing in our system ({count} clients)",
                    "detail": (
                        f"Backoffice shows {sym} for {count} clients but we don't have it. "
                        f"These are likely new positions from a transaction batch we "
                        f"haven't processed yet."
                    ),
                    "affected_clients": count,
                    "symbol": sym,
                })

    # --- 5. Overall health commentary ---
    if summary.total_holdings_bo > 0:
        match_rate = summary.total_holdings_matched / summary.total_holdings_bo * 100
        if match_rate >= 95:
            insights.insert(0, {
                "type": "HEALTH",
                "severity": "good",
                "title": f"Excellent match rate: {match_rate:.1f}%",
                "detail": "Holdings data is well-aligned with the backoffice.",
                "affected_clients": 0,
            })
        elif match_rate >= 70:
            insights.insert(0, {
                "type": "HEALTH",
                "severity": "medium",
                "title": f"Moderate match rate: {match_rate:.1f}%",
                "detail": "Review the insights below for systematic issues to fix.",
                "affected_clients": 0,
            })
        else:
            insights.insert(0, {
                "type": "HEALTH",
                "severity": "critical",
                "title": f"Low match rate: {match_rate:.1f}% — systematic issues detected",
                "detail": (
                    "Most mismatches are likely from corporate actions (stock splits, "
                    "bonuses) that the backoffice applied but our system hasn't adjusted for. "
                    "See specific insights below."
                ),
                "affected_clients": 0,
            })

    # --- 6. NAV vs BO holding total discrepancy ---
    nav_diffs = []
    for c in summary.clients:
        nav_total = getattr(c, "nav_total", None)
        bo_total = getattr(c, "bo_holdings_total", _ZERO)
        if nav_total is not None and nav_total > 0 and bo_total > 0:
            pct_diff = abs(float(nav_total - bo_total)) / float(nav_total) * 100
            if pct_diff > 2:
                nav_diffs.append((c.client_code, pct_diff, nav_total - bo_total))

    if nav_diffs:
        insights.append({
            "type": "NAV_BO_DISCREPANCY",
            "severity": "high" if len(nav_diffs) > 3 else "medium",
            "title": f"NAV vs BO holding total differs >2% for {len(nav_diffs)} clients",
            "detail": (
                "The total NAV value from the NAV file doesn't match the sum of "
                "holding market values from the Holding Report for these clients. "
                "This could indicate unlisted holdings, pending corporate actions, "
                "or timing differences between the two reports."
            ),
            "affected_clients": len(nav_diffs),
        })

    # Sort: critical → high → medium → good
    severity_order = {"critical": 0, "high": 1, "medium": 2, "good": 3}
    insights.sort(key=lambda x: severity_order.get(x["severity"], 99))

    return insights
