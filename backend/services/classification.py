"""Portfolio strategy classification from PMS client/UCC codes.

Single source of truth used by BOTH the one-time merge migration and ongoing
ingestion, so the rules can never drift.

Rules (confirmed with the business):
  - code ends in ``PASS``          -> strategy ``PASSIVE``
  - code ends in ``IND``           -> strategy ``IND11``
  - anything else                  -> strategy ``LEADERS``
  - code ends in ``CLOSE``/``CLO`` -> ``is_closed = True`` (archived: excluded
                                      from live aggregates and the Combined view)

``strategy`` and ``is_closed`` are orthogonal — a closed code keeps whatever
strategy its suffix implies. In the current data every closed code is non
PASS/IND, so they resolve to LEADERS, but the function does not assume that.
"""

from __future__ import annotations

from typing import NamedTuple

STRATEGY_LEADERS = "LEADERS"
STRATEGY_PASSIVE = "PASSIVE"
STRATEGY_IND11 = "IND11"

_PASSIVE_SUFFIX = "PASS"
_IND11_SUFFIX = "IND"
# 'CLOSE' and 'CLO' are both observed (JA59CLOSE, 990NS12CLO). A bare trailing
# 'C' (e.g. 1075SK02C) must NOT be treated as closed, so we only match these two.
_CLOSED_SUFFIXES = ("CLOSE", "CLO")


class Classification(NamedTuple):
    """Result of classifying a client code."""

    strategy: str
    is_closed: bool


def classify_code(code: str | None) -> Classification:
    """Derive ``(strategy, is_closed)`` from a PMS client/UCC code.

    Case-insensitive and whitespace-tolerant. An empty/None code resolves to an
    active LEADERS portfolio (a safe default; empty codes should not occur).
    """
    norm = (code or "").strip().upper()

    is_closed = norm.endswith(_CLOSED_SUFFIXES)

    if norm.endswith(_PASSIVE_SUFFIX):
        strategy = STRATEGY_PASSIVE
    elif norm.endswith(_IND11_SUFFIX):
        strategy = STRATEGY_IND11
    else:
        strategy = STRATEGY_LEADERS

    return Classification(strategy=strategy, is_closed=is_closed)
