"""Ad-hoc smoke test for the file-format detector.

Runs the detector against known-good sample files and verifies:
  1. Correct slot → correct detection (green).
  2. Wrong slot → FileFormatMismatch raised with a clear message (red).

Sample files live in ~/Downloads (local only). No network, no DB.

Usage:
  python3.11 scripts/test_file_format_detector.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.services.file_format_detector import (
    FileFormatMismatch,
    assert_format,
    detect_file_format,
)

DOWNLOADS = Path.home() / "Downloads"
DATA = Path(__file__).resolve().parent.parent / "data"


# (label, path, expected detected format, slots it should be accepted by)
SAMPLES: list[tuple[str, Path, str, list[str]]] = [
    (
        "NAV Report",
        DATA / "NAV Report-01-04-2020 to 16-03-2026.xlsx",
        "NAV",
        ["NAV"],
    ),
    (
        "Transaction Report",
        DATA / "Transaction Report-01-04-2020 to 16-03-2026.xlsx",
        "TRANSACTIONS",
        ["TRANSACTIONS"],
    ),
    (
        "Cash Flow Report",
        DATA / "Cash outflow and inflow-2024-25.xlsx",
        "CASHFLOWS",
        ["CASHFLOWS"],
    ),
    (
        "Equity Holding Report",
        DOWNLOADS / "Holding Report-09-04-2026.xlsx",
        "HOLDINGS",
        ["EQUITY_HOLDINGS", "ETF_HOLDINGS"],
    ),
    (
        "ETF Holding Report",
        DOWNLOADS / "ETF Holding as on 14th April 2026.xlsx",
        "HOLDINGS",
        ["EQUITY_HOLDINGS", "ETF_HOLDINGS"],
    ),
]

ALL_SLOTS = ["NAV", "TRANSACTIONS", "EQUITY_HOLDINGS", "ETF_HOLDINGS", "CASHFLOWS"]


def main() -> int:
    print("=" * 80)
    print("FILE FORMAT DETECTOR — smoke test")
    print("=" * 80)

    failures: list[str] = []

    # ── Phase 1: detect ─────────────────────────────────────────────────────
    print("\n▶ Phase 1: detect each sample")
    for label, path, expected_format, _ok_slots in SAMPLES:
        if not path.exists():
            print(f"  ⚠ SKIP {label}: {path} (file not found)")
            continue
        result = detect_file_format(path)
        status = "✓" if result.detected == expected_format else "✗"
        print(
            f"  {status} {label:25s} → detected={result.detected} "
            f"conf={result.confidence:.0%} row={result.header_row_index}"
        )
        print(f"      preview: {list(result.header_preview[:6])}")
        if result.detected != expected_format:
            failures.append(
                f"{label}: expected {expected_format}, got {result.detected}"
            )

    # ── Phase 2: cross-matrix (every file × every slot) ─────────────────────
    print("\n▶ Phase 2: cross-matrix (file × slot)")
    print(f"  {'':25s} " + " ".join(f"{s:>16s}" for s in ALL_SLOTS))
    for label, path, _expected, ok_slots in SAMPLES:
        if not path.exists():
            continue
        row = [f"  {label:25s}"]
        for slot in ALL_SLOTS:
            expected_accept = slot in ok_slots
            try:
                assert_format(path, slot)
                got_accept = True
            except FileFormatMismatch:
                got_accept = False

            if expected_accept == got_accept:
                symbol = "✓ accept" if got_accept else "✓ reject"
            else:
                symbol = "✗ WRONG"
                failures.append(
                    f"{label} × {slot}: expected "
                    f"{'accept' if expected_accept else 'reject'} "
                    f"but got {'accept' if got_accept else 'reject'}"
                )
            row.append(f"{symbol:>16s}")
        print(" ".join(row))

    # ── Phase 3: sample error messages for a couple of wrong-slot cases ─────
    print("\n▶ Phase 3: wrong-slot error messages")
    wrong_pairs = [
        ("NAV Report",               DATA / "NAV Report-01-04-2020 to 16-03-2026.xlsx",        "TRANSACTIONS"),
        ("Transaction Report",       DATA / "Transaction Report-01-04-2020 to 16-03-2026.xlsx", "EQUITY_HOLDINGS"),
        ("Equity Holding Report",    DOWNLOADS / "Holding Report-09-04-2026.xlsx",              "TRANSACTIONS"),
        ("ETF Holding Report",       DOWNLOADS / "ETF Holding as on 14th April 2026.xlsx",      "NAV"),
    ]
    for label, path, slot in wrong_pairs:
        if not path.exists():
            continue
        try:
            assert_format(path, slot)
            print(f"  ✗ {label} → {slot}: UNEXPECTEDLY ACCEPTED")
            failures.append(f"{label} × {slot} was accepted but should have been rejected")
        except FileFormatMismatch as exc:
            print(f"  ✓ {label} → slot={slot}")
            print(f"      error: {exc.detail[:180]}…")

    # ── Summary ─────────────────────────────────────────────────────────────
    print("\n" + "=" * 80)
    if failures:
        print(f"FAILED — {len(failures)} issue(s):")
        for f in failures:
            print(f"  • {f}")
        return 1
    print("ALL CHECKS PASSED ✓")
    return 0


if __name__ == "__main__":
    sys.exit(main())
