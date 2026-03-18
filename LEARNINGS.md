# Learnings Log
**Project:** JSL Client Portfolio Portal (CPP)
**Rule:** Append-only. Claude logs corrections, discoveries, and patterns here.
**Protocol:** When Nimish corrects something, log it here so the same mistake is never repeated.

---

## L-001: PMS Backoffice Files Are NOT Flat CSVs
**Date:** 2026-03-18
**Category:** Data Ingestion
**Learning:** The NAV and Transaction files from the PMS backoffice are structured reports with embedded headers, date separator rows, and merged columns. Initial assumption of simple CSV with column mapping was wrong. Always inspect actual file samples before designing parsers.
**Impact:** Replaced column_mapper.py approach with stateful nav_parser.py and txn_parser.py.

---

## L-002: NAV is Absolute ₹ Value, Not Normalized Index
**Date:** 2026-03-18
**Category:** Data Model
**Learning:** The "NAV" column in the backoffice export is the absolute portfolio value in ₹ (e.g., ₹50,80,100). It is NOT a normalized base-100 index. For the relative performance chart (base 100), we must compute: `index = (nav_on_date / nav_on_inception_date) * 100`. Same normalization needed for benchmark.
**Impact:** Added TWR Index computation to risk engine. Without this, the chart would show wildly different scales.

---

## L-003: Corpus Changes = XIRR Cash Flows
**Date:** 2026-03-18
**Category:** Financial Calculation
**Learning:** The Corpus column in the NAV file steps up when clients add money (e.g., ₹3.33L → ₹5.33L → ₹10.33L). These step changes ARE the cash flow events needed for XIRR computation. Detecting corpus changes gives us investment dates + amounts without needing a separate cash flow file.
**Impact:** XIRR is client-specific and different from model portfolio CAGR.

---

## L-004: Transaction Rows Can Have Both Buy AND Sell
**Date:** 2026-03-18
**Category:** Data Ingestion
**Learning:** A single row in the transaction file can have non-zero values in BOTH the buy columns (4-11) AND sale columns (12-19). Must check buy_qty and sale_qty independently and create separate transaction records for each.
**Impact:** Parser must not use if/else for buy vs sell — check both.

---

## L-005: "Corpus" Settlement Type = Initial Positions
**Date:** 2026-03-18
**Category:** Data Model
**Learning:** Transactions with Stno="Corpus" are the initial portfolio holdings at inception. These appear as SELL-side entries (sale_qty > 0) because the backoffice records them as the starting inventory. They should be stored as txn_type="CORPUS_IN" — initial positions, not actual sales.
**Impact:** Without this distinction, the P&L calculation would show fake realized losses.

---

## L-006: LIQUIDBEES/LIQUIDETF Are Cash, Not Equity
**Date:** 2026-03-18  
**Category:** Asset Classification
**Learning:** LIQUIDBEES, LIQUIDETF, LIQUIDCASE are liquid fund ETFs used as cash parking instruments. They should be classified as asset_class="CASH", not "EQUITY". The existing NAV file already captures their value in the "Cash And Cash Equivalent" column.
**Impact:** Allocation charts must show these under Cash, not Equity.

---

## L-007: Benchmark Data Not In File — Must Fetch Separately
**Date:** 2026-03-18
**Category:** Data Pipeline
**Learning:** The PMS backoffice NAV file does NOT include benchmark (Nifty 50) values. These must be fetched separately via yfinance and date-aligned with the portfolio NAV series. Missing benchmark dates (market holidays) should be forward-filled.
**Impact:** Added benchmark_service.py to the pipeline. Risk engine depends on this.

---

<!-- Claude will append new learnings here during build sessions -->
