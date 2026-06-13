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

---

## L-008: Two security test suites were silently RED on main (no CI ran them)
**Date:** 2026-06-13
**Category:** Testing / CI
**Learning:** `test_tenant_isolation` and `test_impersonation` were both failing on `main` and nobody knew — there was no CI running `pytest` on PRs. `test_impersonation` called the auth dependencies without a DB session, but auth had since been refactored to re-validate the token against the DB (`_validate_client_from_db`, C5); the tenant suite's `_make_cookies` omitted the now-required `token_version`. Both were repaired (the impersonation one now seeds an in-memory session and exercises the real C5 path).
**Impact:** Added `.github/workflows/tests.yml` (PR gate). **Always run the full suite — not just compile — and treat a stale security test as a real gap.** When a dependency's signature/behaviour changes, grep its callers in tests.

---

## L-009: Reconcile combined/aggregate against sum-of-parts; ₹ adds, ratios don't
**Date:** 2026-06-13
**Category:** Math / Aggregation
**Learning:** For the Combined view (and admin aggregate), only ₹ quantities are additive (AUM, invested, holding value/qty). Returns/ratios (CAGR, Sharpe, beta, XIRR, max DD) must be **recomputed from the combined TWR/composite series**, never summed. Every aggregate function ships with a reconciliation test asserting `combined == sum of the client's live portfolios`. Two edges bit us: (a) the shared `max_drawdown()` argmax-errors on a monotonic series (trough at index 0) — compute drawdown inline; (b) SQLite returns `nav_date` as a string while Postgres returns a `date` — normalise with `pd.to_datetime(...).dt.date` so date math works in both tests and prod.
**Impact:** `combined_service.py` / `combined_analytics.py` use inline drawdown + date normalisation; reconciliation tests guard the invariant.

---

## L-010: Agent sessions need a test-deps bootstrap; RDS only reachable via EC2
**Date:** 2026-06-13
**Category:** Environment / Ops
**Learning:** Backend test deps aren't preinstalled in agent containers — `pip install` the set in `HANDOFF_MULTIPORTFOLIO.md §5` (incl. `aiosqlite`, and `cffi` to fix the system `cryptography` panic) before `pytest`. The suite runs entirely on SQLite (no RDS). RDS is **not** reachable from agent sessions directly — tunnel via EC2 (`INFRA_ACCESS.md`) or run scripts on the box (`clients.jslwealth.in` = `13.206.34.214`, app at `~/apps/client-portal`, `DATABASE_URL_SYNC` in `.env`, use `docker run postgres:15 --network host` for `psql`).
**Impact:** CI (`tests.yml`) sets dummy `DATABASE_URL`/`JWT_SECRET` (format-valid, never dialled). Prod DB work is a gated, on-box step.

---

## L-011: A merge migration's verifier must check DURABLE invariants, not snapshots-in-time
**Date:** 2026-06-13
**Category:** Migrations / Data Integrity
**Learning:** Building PR7a (client merge), a high-effort review caught several traps worth remembering:
- **Don't re-validate cross-time facts.** The first `verify_merge_invariants` asserted every retired client still shares its survivor's *current* name. But a survivor's name can be edited post-merge — that would make a future, correct merge run fail forever. Name-grouping is now asserted **at merge time** (where it's the actual invariant); verify only checks **durable** facts (AUM/invested/portfolio-count unchanged, cross-table ownership, dangling FKs, zero orphans, no chains).
- **INNER JOIN hides orphans.** An ownership check joined data→portfolio with an INNER JOIN, so a row pointing at a missing portfolio was invisible. Added an explicit dangling-FK (`portfolio_id NOT IN (...)`) check.
- **`(client_id, portfolio_name)` is unique** and every portfolio is `"PMS Equity"` — re-parenting must rename (to `"PMS Equity (<code>)"`); `client_code` is the globally-unique disambiguator.
- **Auth alias: deny > strand.** A retired login whose survivor is gone/disabled must be denied, not landed on the emptied retired account; and chains (`A→B→C`) must be followed to the terminal survivor (with a cycle guard).
- **Engine-agnostic SQL** (no `DISTINCT ON`/`FILTER`/`ON CONFLICT`, no window-function reliance) lets the CI fixture run the *real* migration on SQLite — the strongest possible test. Pick exactly one row per group with a `MAX(id)`-at-`MAX(date)` subquery to match Postgres `DISTINCT ON` deterministically.
- **CLI ordering:** write side-artifacts (credential CSV) **after** commit so a filesystem error can't roll back a verified merge; validate `--expect-*` guards up front so a typo aborts cleanly, not with a `Decimal` traceback.
**Impact:** `merge_service.py` / `merge_clients_by_name.py` reflect all of the above; `tests/test_merge_service.py` seeds a prod-shaped DB (multi-code person + single-code + closed + admin + soft-deleted-same-name) and runs the real migration in CI, asserting every invariant + alias resolution.
