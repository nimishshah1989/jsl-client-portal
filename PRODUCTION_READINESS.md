# Production Readiness — JSL Client Portfolio Portal

**Created:** 2026-05-26
**Source:** Four-agent audit (security, code-quality, accuracy, bug-hunt) consolidated 2026-05-26
**Yardstick:** OWASP ASVS L2 + DPDP Act 2023
**Verdict:** ⚠️ NOT READY for 200-client launch. ~10–14 engineering days to defensible production.
**Status:** Active remediation in progress

> **Read this file at session start.** It is the single source of truth for the production-launch backlog. Each item has an owner, sprint, severity, and acceptance criteria. Update the checkbox + add a note when you close one.

---

## Aggregate Severity Counts

| Severity | Count | Sprint |
|---|---|---|
| Critical / P0 | **17** | Sprint 1 + 2 |
| High / P1 | 22 | Sprint 2 + 3 |
| Medium / P2 | 17+ | Sprint 3 + 4 |
| Low / P3 | 13+ | Sprint 4 + backlog |

**Grades:** Code health B− · Math correctness B (3 formula deviations) · Tenant isolation C (no automated test).

---

## Recurring Theme

Code/schema for the right things exists; **it isn't wired up**. Encryption module → never called. Audit table → silent on reads/uploads. `revoked_at` / `is_deleted` columns → no endpoints set them. `role` enum (`ADMIN_READONLY`/`ADMIN_FULL`) → only `is_admin` boolean enforced. `token_version` → not present, so logout doesn't invalidate JWTs.

---

## Sprint 1 — Safety Net (3–4 days, BLOCKING launch)

Auth/cookie/JWT/encryption changes touch overlapping files. **Run sequentially, one PR per item.**

| # | ID | Title | Files | Status | Notes |
|---|---|---|---|---|---|
| 1 | C1 | Rotate `fie_admin` RDS password + scrub old credentials from git history | AWS console + `git filter-repo` | ☑ 2026-05-26 | **DB migrated to jip-data-engine** (accessible, same AWS account). `client_portal` DB created; `fie_admin` role created with new password; all 11 cpp_ tables created with `fie_admin` as owner; EC2 `.env` updated → container healthy at `http://localhost:8007/api/health`. ⚠️ Remaining: scrub old DB credentials from `CLAUDE.md` git history using `git filter-repo`. ENCRYPTION_KEY not yet generated — **must add before deploying C3 (PR #12)**. Generate: `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` |
| 2 | C2 | RDS TLS `verify_mode=CERT_REQUIRED` + bundle `rds-combined-ca-bundle.pem` | `backend/database.py`, `Dockerfile` | ☑ 2026-05-26 | PR #11 — `global-bundle.pem` downloaded at build time; `ssl.SSLContext` with `CERT_REQUIRED` wired into `create_async_engine` |
| 3 | C3 | Wire `encrypt_pii`/`decrypt_pii` `TypeDecorator` for `Client.email`, `phone`, `AuditLog.ip_address`. Make `ENCRYPTION_KEY` required in prod. | `backend/utils/encryption.py`, `backend/models/client.py`, `backend/models/audit_log.py`, `backend/config.py` | ☑ 2026-05-26 | PR #12 — **DEPLOY NOTE:** Run `ALTER TABLE cpp_clients ALTER COLUMN email TYPE VARCHAR(500), ALTER COLUMN phone TYPE VARCHAR(100); ALTER TABLE cpp_audit_log ALTER COLUMN ip_address TYPE VARCHAR(200);` before deploying. Generate key: `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` |
| 4 | C5 | JWT `token_version` revocation + re-validate `is_admin` from DB | `backend/middleware/auth_middleware.py`, `backend/models/client.py`, `backend/routers/auth.py` | ☑ 2026-05-26 | PR #9 — `tv` claim in JWT; DB check on every request; bumped on logout + password-change |
| 5 | C4 | `log_audit("VIEW")` on every `/api/portfolio/*` read | All `backend/routers/portfolio*.py` | ☑ 2026-05-26 | PR #10 — all 11 portfolio GET endpoints covered |
| 6 | C17 | Back-nav cookie-collision fix: separate `impersonation_token` cookie, new `POST /api/admin/stop-impersonate`, `/login` auto-redirect logged-in users, `/dashboard/layout` admin-gate | `backend/routers/admin.py`, `backend/routers/auth.py`, `frontend/src/app/login/page.js`, `frontend/src/app/dashboard/layout.js`, `backend/middleware/auth_middleware.py` | ☑ 2026-05-26 | PR #7 — **This is the reported "fail to load" bug.** Merge first. |
| 7 | C16 | Bind FastAPI to `127.0.0.1`; container non-root user; xlsx zip-bomb guard (200 MB cap); `/tmp` upload → `/app/data/uploads` | `Dockerfile`, `start.sh`, `backend/routers/admin_upload.py` | ☑ 2026-05-26 | PR #11 |
| 8 | H3 | Per-username login lockout (10 fails → 30 min lock); rate-limit `/change-password` (5/hour) | `backend/models/client.py`, `backend/routers/auth.py` | ☑ 2026-05-26 | PR #9 |
| 9 | C6 | `is_password_set` boolean on `cpp_clients`; block login until True | `backend/models/client.py`, `backend/routers/auth.py` | ☑ 2026-05-26 | PR #9 — **DEPLOY NOTE:** `ALTER TABLE cpp_clients ADD COLUMN IF NOT EXISTS is_password_set BOOLEAN NOT NULL DEFAULT false, ADD COLUMN IF NOT EXISTS token_version INT NOT NULL DEFAULT 1, ADD COLUMN IF NOT EXISTS failed_login_count INT NOT NULL DEFAULT 0, ADD COLUMN IF NOT EXISTS locked_until TIMESTAMP;` |

---

## Sprint 2 — Math + Accuracy (2–3 days, BLOCKING launch)

These are partially independent — math/test/recon/filter streams can run in parallel (different files).

| # | ID | Title | Files | Status | Notes |
|---|---|---|---|---|---|
| 10 | C8 | Fix `absolute_return` label collision: either rename column to `adjusted_return_weighted` OR restore spec formula `(end/start − 1)` | `backend/services/risk_engine.py:281-292`, `backend/services/risk_metrics.py:97-114`, `backend/models/risk_metric.py` | ☐ | Decision needed: rename vs revert |
| 11 | C9 | Align Sharpe: spec is `(CAGR − Rf) / σ_p` annualized; current code uses daily-excess mean/std × √252 | `backend/services/risk_metrics.py:142-161` | ☐ | Decide which formula to ship; update Methodology copy to match |
| 12 | C10 | Align Sortino: spec downside threshold is **zero**; code uses **daily Rf** | `backend/services/risk_metrics.py:164-188` | ☐ | Same as C9 — must reconcile against Market Pulse |
| 13 | C12 | Transaction filter param-name mismatch | `backend/routers/portfolio_detail.py`, `frontend/src/components/dashboard/TransactionHistory.jsx` | ☑ 2026-05-26 | PR #2 |
| 14 | C14 | Multi-tenant isolation test | `tests/test_tenant_isolation.py` | ☑ 2026-05-26 | PR #6 — 26 tests, all passing |
| 15 | C11 | Reconciliation gates client view: `is_recon_clean` flag → block login OR show "Data being reconciled" banner | `backend/models/client.py`, `backend/routers/auth.py`, `frontend/src/app/dashboard/layout.js` | ☐ | UX decision: block vs warn |
| 16 | C7 | Persistent upload-job state: replace in-memory `_upload_jobs` dict with `cpp_upload_log` row in `processing` state | `backend/routers/admin_upload.py:155`, `backend/models/upload_log.py` | ☐ | Needed for multi-worker correctness |
| 17 | C13 | Stock-split + corporate-actions auto-apply | New table, `backend/services/holdings_service.py` | ☐ | Larger; design first |
| 18 | C15 | Tech-docs page auth gate verified; split 1014-line file | `frontend/src/app/tech-docs/page.js`, `frontend/src/app/tech-docs/layout.js` | ◐ 2026-05-26 | Auth gate added (admin-only) — verified prior layout had no gating; file-split (F1) still pending |
| — | — | XIRR robustness: return `None` on non-convergence; sort cash flows ascending; widen bracket | `backend/services/xirr_service.py` | ☑ 2026-05-26 | PR #5 |
| — | — | Decimal-at-boundary: `live_prices.py` + `ingestion_helpers.py` | `backend/services/live_prices.py`, `backend/services/ingestion_helpers.py` | ☑ 2026-05-26 | PR #4 |
| — | — | Benchmark flat series fix + N/A for insufficient history | `backend/services/benchmark_service.py`, `backend/services/risk_engine.py`, `backend/services/risk_db.py` | ☑ 2026-05-26 | PR #8 — **run POST /api/admin/recompute-risk after deploy** |

---

## Sprint 3 — DPDP Rights + Ops (2–3 days)

Parallel-safe — each endpoint is a new file.

| # | ID | Title | Files | Status |
|---|---|---|---|---|
| 19 | DPDP §11 | `GET /api/me/export` — return all client data as JSON (DSAR) | new router | ☐ |
| 20 | DPDP §12 | `POST /api/me/erasure-request` — initiate erasure; cascade to NAV/transactions/holdings | new router + service | ☐ |
| 21 | DPDP §7 | `POST /api/me/consent/withdraw` — set `cpp_client_consents.revoked_at` | new router | ☐ |
| 22 | DPDP §13 | Grievance redressal endpoint + DPO contact | new router, privacy policy link in footer | ☐ |
| 23 | M2 | Enforce `role` enum (ADMIN_READONLY/ADMIN_DATA_ENTRY/ADMIN_FULL) in `get_admin_user(required_role=...)` | `backend/middleware/auth_middleware.py:84`, all `routers/admin*.py` | ☐ |
| 24 | M9 | Filter `is_deleted=false` from admin client list + block impersonation of soft-deleted | `backend/routers/admin_clients.py:34`, `backend/routers/admin.py:466` | ☐ |
| 25 | M7 | Audit log writes on separate connection (commit even when business txn rolls back); revoke UPDATE/DELETE on `cpp_audit_log` from app role | `backend/services/audit_service.py:30-45`, DB grants | ☐ |
| 26 | M3 | Default-on HSTS unless `APP_ENV=development`; fail startup if `APP_ENV` unset; default-on secure cookies | `backend/middleware/security.py:43`, `backend/routers/auth.py:40`, `backend/main.py` lifespan | ☐ |
| 27 | M5 | Reduce JWT expiry to 60 min access + rotating 8h refresh token | `backend/config.py:29`, `.env.example:14`, `backend/routers/auth.py` | ☐ |
| 28 | H1 | CSRF default-deny on all unsafe methods regardless of auth state | `backend/middleware/security.py:62-77` | ☐ |
| 29 | H4 | Separate `cpp_app` (DML) and `cpp_migrator` (DDL) DB roles; migrations from CI not container | `start.sh:8-9`, deploy docs | ☐ |
| 30 | M6 | Bulk-create CSV: apply `validate_password_complexity`; force `must_change_password=true`; replace WhatsApp distribution with signed activation link | `backend/routers/admin_clients.py:117`, `backend/schemas/auth.py:47` | ☐ |
| 31 | M8 | Strict CORS origin validation (`^https?://[a-z0-9.-]+(:\d+)?$`); reject `*`; warn on >1 origin in prod | `backend/main.py:87-94`, `backend/config.py:84-86` | ☐ |
| 32 | M4 | Drop `unsafe-eval` from CSP; per-request nonce middleware for `script-src` | `backend/middleware/security.py:47` | ☐ |

---

## Sprint 4 — Quality + Polish (3–4 days)

Fully parallel-safe — different files.

| # | ID | Title | Status |
|---|---|---|---|
| 33 | A1 | Adopt Alembic; baseline from `Base.metadata`; retire `auto_migrate.py` | ☐ |
| 34 | A4 | Replace `useApiData` with TanStack Query / SWR | ☐ |
| 35 | Q1 | Frontend `ErrorBoundary` around each dashboard section | ☐ |
| 36 | Q2 | `AbortController` on all `apiFetch` calls; bail before `setState` on abort | ☐ |
| 37 | Q3 | Lift user into a React Context provider (eliminate duplicate `/auth/me` calls) | ☐ |
| 38 | A3 | Centralized `decimal_to_pandas_series` / `pandas_value_to_decimal` utilities with explicit NaN/inf handling | ☐ |
| 39 | A2 | Persist upload jobs (covered by C7 in Sprint 2) | ☐ Done with C7 |
| 40 | F1 | Split files > 400 lines (10 files; see table below) | ☐ |
| 41 | Q4 | Project-wide tz discipline: store everything UTC-aware; reject naive Timestamps at API boundary | ☐ |
| 42 | Q5 | Recharts null-guards (`Number(entry.value ?? 0)` etc.); chart-level error boundary | ☐ |
| 43 | Q6 | XIRR / cash_metrics / capture-ratio NaN guards | ☐ |
| 44 | T1 | Add the 5 must-have tests: end-to-end risk engine, holdings-after-bonus, XIRR multi-infusion+redemption, tenant isolation, upload idempotency | ☐ (tenant covered by C14) |

**Oversized files (>400 lines, CLAUDE.md violation):**

| File | Lines | Split target |
|---|---|---|
| `frontend/src/app/tech-docs/page.js` | 1014 | one file per top-level Section, target 8–10 files |
| `backend/services/ingestion_service.py` | 643 | `nav_ingest.py`, `txn_ingest.py`, `equity_holdings_ingest.py`, `etf_holdings_ingest.py`, `cashflow_ingest.py`, `ingest_common.py` |
| `backend/services/reconciliation_service.py` | 640 | extract `reconciliation_matchers.py`; keep orchestration thin |
| `backend/services/ingestion_helpers.py` | 621 | `client_upsert.py`, `nav_upsert.py`, `txn_upsert.py`, `holdings_recompute.py` |
| `backend/services/risk_engine.py` | 546 | extract `risk_engine_batch.py` |
| `backend/routers/admin_reconciliation.py` | 508 | move `/export` + `/sync-costs` out |
| `backend/routers/admin.py` | 496 | split impersonation + analytics |
| `backend/services/holding_report_parser.py` | 446 | push header detection into `holding_report_format.py` |
| `backend/services/aggregate_service.py` | 440 | separate `aggregate_nav_composition.py` from `aggregate_metrics.py` |
| `backend/services/txn_parser.py` | 423 | extract `TxnParserState` |

---

## Pre-Launch Verification Gate

**Sign-off required from BACKEND + QA before first client URL is shared.** No exceptions.

- [ ] V1. BJ53 sample loaded; inception/latest-NAV/corpus/current-NAV match PMS report exactly
- [ ] V2. Performance Table side-by-side vs `marketpulse.jslwealth.in/portfolios?id=4`: every cell (1M/3M/6M/1Y/2Y/3Y/Inception × Abs/CAGR/Vol/MaxDD/Sharpe/Sortino) within ±0.5%
- [ ] V3. Hand-compute Sharpe both ways; Methodology copy matches code (closes C9)
- [ ] V4. Hand-compute XIRR for 3-event series; matches Excel within 0.01%
- [ ] V5. Re-upload same NAV file twice; row counts unchanged; risk not recomputed
- [ ] V6. Transactions before NAV → clear "NAV missing" UX, not zeroes
- [ ] V7. Reconciliation against known-clean BO Holding Report; all matched clients show `match_pct = 100`
- [ ] V8. Deliberate QTY_MISMATCH → admin page surfaces AND client dashboard banners or gates
- [ ] V9. Every Sharpe/Sortino number on dashboard derivable from Methodology page inputs
- [ ] V10. Multi-tenant isolation test passes in CI (closes C14)
- [ ] V11. Decimal precision: ₹1234.5678 round-trips DB → API → dashboard at correct precision
- [ ] V12. `is_password_set` blocks login for any auto-created client (closes C6)

---

## Workflow Per Fix

```
1. Plan agent (subagent_type: Plan)   → design + blast radius + test cases
2. Implement                            → general-purpose agent w/ isolation: worktree
3. /code-review --comment              → effort=high on the diff
4. /security-review                     → MANDATORY for any auth/cookie/PII/audit change
5. /verify                              → run the app, exercise the changed path in a browser
6. Push branch + draft PR + subscribe_pr_activity
7. User reviews + merges
```

**Parallel rules:**
- Auth/JWT/cookie changes touch overlapping files — **sequential within Sprint 1**.
- Math fixes, tests, refactors, frontend Q-items are non-overlapping — **parallel-safe**.
- Each parallel agent works in a worktree on a sub-branch (e.g. `claude/stoic-babbage-xgPme-math`) and opens its own draft PR.

---

## Out-of-Scope for Launch (Tracked for Later)

- L1–L5 (Low severity headers)
- 4-week SOC2 readiness package
- Multi-region DR
- Replacing yfinance with paid market-data feed
- Native mobile app

---

## Change Log

| Date | Author | Change |
|---|---|---|
| 2026-05-26 | Audit synthesis (Claude) | Initial backlog created from 4-agent audit |
| 2026-05-26 | Claude (session 2) | Sprint 1 complete (8/9 items): C2, C3, C4, C5, C6, C16, C17, H3 → PRs #7–#12. C1 blocked (fie-db RDS inaccessible — DB connection broken, needs operator resolution). Sprint 2 partial: C12, C14, XIRR, Decimal, Benchmark → PRs #2–#8. |
| 2026-05-26 | Claude (session 3) | C1 resolved: migrated `client_portal` DB from fie-db (inaccessible) to jip-data-engine (same AWS account). Created `fie_admin` role + fresh password. All 11 cpp_ tables created with full schema (includes C5/C6/H3 columns: `token_version`, `is_password_set`, `failed_login_count`, `locked_until`; email/phone/ip_address already at widened VARCHAR sizes for C3 encryption). Container healthy. **ENCRYPTION_KEY still needed in .env before deploying PR #12.** **ALTER TABLE deploy notes in PR #9 and PR #12 already applied — DB schema is ahead of deployed code.** PRs #7–#12 still pending merge + deploy. |
