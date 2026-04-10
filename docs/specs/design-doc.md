# Design Doc: Holdings Reconciliation Module + NAV Upload Performance Fix

## Problem Statement

### 1. Holdings Reconciliation
The PMS backoffice exports a **Holding Report** (.xlsx) — the authoritative source of truth for every client's current positions. Our system computes holdings independently from transaction history using weighted average cost. There is no way to verify our computed holdings match the backoffice. We need a reconciliation module that:
- Parses the backoffice Holding Report
- Compares it field-by-field against our `cpp_holdings`
- Surfaces mismatches (quantity, avg cost, market value) per client per symbol
- Gives admin a clear dashboard to investigate and resolve discrepancies

### 2. NAV Upload Performance
NAV file uploads (~200 clients, ~1000+ NAV rows per client) are slow because:
- **Row-by-row INSERTs**: `upsert_nav_rows()` executes individual INSERT...ON CONFLICT per row (~200K round-trips for a full file)
- **Row-by-row benchmark UPDATEs**: `update_benchmark_values()` executes individual UPDATE per date per client
- **Sequential client processing**: Each client waits for the previous to finish (parse → upsert → benchmark fetch → risk engine)
- **Per-client yfinance calls**: Benchmark data fetched per client (cache helps but still N lookups)
- **Risk engine runs per-client during upload**: Blocks the upload pipeline

---

## Holding Report Format (Backoffice)

```
Columns (16):
UCC | Family Group | Share (PMS) | ISIN | Stock (qty) | Cost (Rs.) | Total Cost |
% Holding Cost | % Holding Cost Cumul | Market Rate | Market Rate Date |
Market Value (Rs.) | Notional P/L | ROI [%] | % Holding Market | % Cumul
```

- **253 unique UCCs**, **1718 holding rows**
- UCC maps to our `client_code` (e.g., "ML08PASS", "AT72", "AZ08")
- "Family Group" = portfolio strategy name ("Passive Portfolio", "Momentum Leaders", etc.)
- Share column has trailing whitespace + instrument suffix: `"CPSEETF EQ                    "` → symbol `CPSEETF`
- ISIN available for reliable matching
- Market Rate Date: `08/04/2026` — need to compare against same-date prices
- Cost = per-share avg cost, Total Cost = qty × cost

---

## Architecture

### Reconciliation Flow
```
Admin uploads Holding Report .xlsx
        │
        ▼
holding_report_parser.py  →  Normalized DataFrame
        │                     (ucc, symbol, isin, qty, avg_cost,
        │                      total_cost, mkt_price, mkt_value, pnl, roi, weight)
        ▼
reconciliation_service.py  →  Match by (client_code + symbol)
        │                      Compare: qty, avg_cost, mkt_price, mkt_value, pnl
        │                      Categorize: MATCH / QTY_MISMATCH / COST_MISMATCH /
        │                                  MISSING_IN_OURS / EXTRA_IN_OURS
        ▼
Store results in cpp_reconciliation table
        │
        ▼
API endpoints → Admin UI dashboard
```

### NAV Upload Optimization
```
BEFORE (per-client sequential):
  for client in clients:
    for row in client_rows: INSERT one row     ← N*M round-trips
    for date in dates: UPDATE benchmark        ← N*D round-trips  
    run_risk_engine()                          ← blocks upload

AFTER (bulk + deferred):
  Pre-fetch benchmark data ONCE (all dates)    ← 1 yfinance call
  for client in clients:
    Bulk INSERT client_rows (executemany)       ← 1 statement per client
    Bulk UPDATE benchmark (CASE/WHEN)           ← 1 statement per client
    commit
  THEN: run risk engine for all affected clients (can be async/deferred)
```

---

## Chunks

### Chunk 1: NAV Upload Performance Fix
**Files:** `backend/services/ingestion_helpers.py`, `backend/services/ingestion_service.py`
**Changes:**
- `upsert_nav_rows()` → bulk INSERT using `executemany` or VALUES list
- `update_benchmark_values()` → pre-fetch benchmark once, bulk UPDATE with CASE/WHEN
- `ingest_nav_file()` → pre-fetch benchmark before client loop, separate risk computation phase
**Acceptance:** Upload of 200-client NAV file completes in <60s (vs current 5-10min)

### Chunk 2: Holding Report Parser
**Files:** NEW `backend/services/holding_report_parser.py`
**Changes:**
- Parse .xlsx with openpyxl read_only mode
- Normalize: strip whitespace from UCC/symbol, extract symbol from "SYMBOL EQ" format
- Return list of dicts with standardized field names
**Acceptance:** Parser returns 1718 rows with correct UCC, symbol, qty, cost, value for sample file

### Chunk 3: Reconciliation Engine
**Files:** NEW `backend/services/reconciliation_service.py`
**Changes:**
- Load backoffice data (from parser) + our holdings (from DB)
- Match by client_code + symbol (with normalization)
- Compute diffs with tolerance (cost: ±₹0.01, qty: exact, value: ±₹1)
- Return structured results: matches, mismatches by category, summary stats
**Acceptance:** Correctly identifies matches and mismatches for all 253 clients

### Chunk 4: Reconciliation API
**Files:** NEW `backend/routers/admin_reconciliation.py`, `backend/schemas/reconciliation.py`
**Changes:**
- `POST /api/admin/upload-holdings-report` — upload + parse + reconcile
- `GET /api/admin/reconciliation/summary` — overview stats
- `GET /api/admin/reconciliation/detail?client_code=XX` — per-client breakdown
- `GET /api/admin/reconciliation/export` — CSV download of mismatches
**Acceptance:** All endpoints return correct data, admin-only auth

### Chunk 5: Reconciliation Admin UI
**Files:** NEW `frontend/src/app/admin/reconciliation/page.js`, NEW components
**Changes:**
- Upload section for Holding Report
- Summary cards: total clients, matched %, qty mismatches, cost mismatches, missing
- Client-level table with expandable rows showing side-by-side comparison
- Filter by mismatch type
- CSV export button
**Acceptance:** Full reconciliation workflow works end-to-end via admin UI
