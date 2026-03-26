# Retrofit Report — JSL Client Portfolio Portal (CPP)
_Generated: 2026-03-24_

## Quality Score: 38/100

| Category | Score | Weight | Weighted |
|----------|-------|--------|----------|
| Test Coverage | 0/20 | 20% | 0 |
| File Size Compliance | 12/15 | 15% | 12 |
| Financial Code Safety | 8/20 | 20% | 8 |
| Type Safety | 0/10 | 10% | 0 |
| Security | 8/15 | 15% | 8 |
| Error Handling | 8/10 | 10% | 8 |
| Dead Code/TODOs | 10/10 | 10% | 10 |
| **Total** | | | **38** |

---

## Critical Issues (fix immediately)

- [ ] **CRIT-1: Zero test coverage — no test files, no test frameworks installed** — 88 source files, 0 test files. Neither pytest nor Jest/Vitest are in dependencies. The commit gate hook cannot function. **Fix:** Install pytest + httpx (Python), vitest + @testing-library/react (JS). Write tests for risk_engine, auth, ingestion pipeline first.

- [ ] **CRIT-2: python-jose has known CVEs (CVE-2024-33663, CVE-2024-33664)** — `requirements.txt:python-jose[cryptography]==3.3.0` — Unmaintained package with JWT validation bypass vulnerabilities. **Fix:** Replace with `PyJWT>=2.8.0` or `joserfc`. Update `backend/services/auth_service.py` JWT encode/decode calls. Effort: S.

- [ ] **CRIT-3: passlib is unmaintained (last release 2020)** — `requirements.txt:passlib[bcrypt]==1.7.4` — Known compatibility issues with bcrypt 4.x, no security patches. **Fix:** Replace with direct `bcrypt` usage (`bcrypt.hashpw`/`bcrypt.checkpw`) or use `argon2-cffi`. Update `backend/services/auth_service.py`. Effort: S.

- [ ] **CRIT-4: 5 files exceed 400-line limit** — Must split:

| File | Lines | Suggested Split |
|------|-------|----------------|
| `frontend/src/app/dashboard/methodology/page.js` | 536 | Extract section renderers into `methodology-renderers.js` |
| `backend/routers/portfolio.py` | 528 | Split into `portfolio_summary.py` + `portfolio_charts.py` |
| `backend/services/risk_metrics.py` | 481 | Split into `risk_metrics_core.py` + `risk_metrics_monthly.py` |
| `backend/routers/portfolio_detail.py` | 473 | Split into `portfolio_risk.py` + `portfolio_xirr.py` |
| `frontend/src/lib/methodology-sections.js` | 450 | Split into `methodology-returns.js` + `methodology-risk.js` + `methodology-benchmark.js` |

---

## Major Issues (fix this sprint)

- [ ] **MAJ-1: 60+ float() calls in financial computation code** — `backend/services/risk_metrics.py` has 22 float() calls, `backend/routers/portfolio.py` has 8, `backend/services/xirr_service.py` has 5. Risk metrics are computed in float and returned without Decimal conversion. **Fix:** Keep float for numpy operations, but wrap all return values with `Decimal(str(result)).quantize(...)` before DB write or API response. Effort: M.

- [ ] **MAJ-2: risk_metrics.py functions return raw float, not Decimal** — `backend/services/risk_metrics.py` — All 22 metric functions return `float(...)`. The `risk_db.py:to_decimal()` converter exists but isn't consistently applied. **Fix:** Add `to_decimal()` conversion at the boundary in `risk_engine.py` before writing to DB. Effort: M.

- [ ] **MAJ-3: No TypeScript — zero compile-time type safety on frontend** — All 40 frontend files are plain `.js/.jsx`. No JSDoc annotations either. **Fix:** Migrate incrementally — start with `lib/` utilities and hooks, then components. Or add JSDoc `@typedef` and `@param` annotations. Effort: L.

- [ ] **MAJ-4: No rate limiting on auth endpoints** — `backend/routers/auth.py` — Login endpoint has no rate limiter, enabling brute-force attacks. **Fix:** Add `slowapi` rate limiter: 5 attempts/minute per IP on `/api/auth/login`. Effort: S.

- [ ] **MAJ-5: Silent exception swallowing in holdings_service.py** — `backend/services/holdings_service.py:35` — `except Exception: return _ZERO` silently converts ANY error to zero, masking data corruption. **Fix:** Catch specific exceptions (`ValueError`, `InvalidOperation`), log unexpected exceptions before returning default. Effort: S.

- [ ] **MAJ-6: txn_parser.py uses _safe_float() for financial amounts** — `backend/services/txn_parser.py:98-103` — Transaction quantities and amounts parsed as float via `_safe_float()`. **Fix:** Replace with `_safe_decimal()` using `Decimal(str(value))`. Effort: S.

- [ ] **MAJ-7: cashflow_parser.py parses amounts as float** — `backend/services/cashflow_parser.py:93-94,138-143` — Cash flow amounts (critical for XIRR) parsed as float. **Fix:** Use `Decimal(str(...))` for all amount parsing. Effort: S.

---

## Minor Issues (fix when touching the file)

- [ ] **MIN-1: bcrypt version outdated** — `requirements.txt:bcrypt==4.0.1` — Current stable is 4.2.x. **Fix:** Update to `bcrypt>=4.2.0`. Effort: S.

- [ ] **MIN-2: yfinance unpinned upper bound** — `requirements.txt:yfinance>=1.2.0` — Could break on major version bump. **Fix:** Pin to `yfinance>=1.2.0,<2.0`. Effort: S.

- [ ] **MIN-3: 12 files in 200-400 line range approaching limit** — See file size audit table below. Monitor and split proactively when adding features.

---

## Test Gap Analysis

### Backend (Python)

| Source File | Test File | Status |
|------------|-----------|--------|
| backend/main.py | — | :x: Missing |
| backend/config.py | — | :x: Missing |
| backend/database.py | — | :x: Missing |
| backend/models/*.py (8 files) | — | :x: Missing |
| backend/routers/auth.py | — | :x: Missing |
| backend/routers/portfolio.py | — | :x: Missing |
| backend/routers/portfolio_detail.py | — | :x: Missing |
| backend/routers/admin.py | — | :x: Missing |
| backend/services/auth_service.py | — | :x: Missing |
| backend/services/risk_engine.py | — | :x: Missing |
| backend/services/risk_metrics.py | — | :x: Missing |
| backend/services/risk_db.py | — | :x: Missing |
| backend/services/ingestion_service.py | — | :x: Missing |
| backend/services/ingestion_helpers.py | — | :x: Missing |
| backend/services/nav_parser.py | — | :x: Missing |
| backend/services/txn_parser.py | — | :x: Missing |
| backend/services/cashflow_parser.py | — | :x: Missing |
| backend/services/xirr_service.py | — | :x: Missing |
| backend/services/holdings_service.py | — | :x: Missing |
| backend/services/benchmark_service.py | — | :x: Missing |
| backend/services/stock_reference.py | — | :x: Missing |
| backend/services/live_prices.py | — | :x: Missing |
| backend/services/scheduler.py | — | :x: Missing |
| backend/utils/*.py | — | :x: Missing |

### Frontend (JS/JSX)

| Source File | Test File | Status |
|------------|-----------|--------|
| src/hooks/useAuth.js | — | :x: Missing |
| src/hooks/usePortfolio.js | — | :x: Missing |
| src/hooks/useAdmin.js | — | :x: Missing |
| src/lib/api.js | — | :x: Missing |
| src/lib/format.js | — | :x: Missing |
| src/components/dashboard/*.jsx (11 files) | — | :x: Missing |
| src/app/login/page.js | — | :x: Missing |
| src/app/dashboard/page.js | — | :x: Missing |
| src/app/admin/page.js | — | :x: Missing |

**Total: 88 source files, 0 test files, 0% coverage.**

---

## Files Over 400 Lines (Must Split)

| File | Lines | Suggested Split | Effort |
|------|-------|----------------|--------|
| `frontend/src/app/dashboard/methodology/page.js` | 536 | `methodology-renderers.js` (section render functions) | S |
| `backend/routers/portfolio.py` | 528 | `portfolio_summary.py` (summary/nav/growth) + `portfolio_charts.py` (allocation/drawdown) | M |
| `backend/services/risk_metrics.py` | 481 | `risk_metrics_core.py` (returns/vol/sharpe) + `risk_metrics_monthly.py` (monthly profile/streaks) | M |
| `backend/routers/portfolio_detail.py` | 473 | `portfolio_risk.py` (scorecard/methodology) + `portfolio_xirr.py` (xirr/cashflows) | M |
| `frontend/src/lib/methodology-sections.js` | 450 | `methodology-returns.js` + `methodology-risk.js` + `methodology-benchmark.js` | S |

---

## Files Approaching Limit (200-400)

| File | Lines |
|------|-------|
| `backend/services/risk_engine.py` | 381 |
| `scripts/reset_credentials.py` | 376 |
| `backend/services/ingestion_helpers.py` | 369 |
| `backend/routers/admin.py` | 362 |
| `scripts/seed_test_clients.py` | 353 |
| `frontend/src/components/dashboard/TransactionHistory.jsx` | 321 |
| `frontend/src/components/layout/Sidebar.jsx` | 293 |
| `backend/services/ingestion_service.py` | 289 |
| `backend/services/txn_parser.py` | 283 |
| `backend/services/stock_reference.py` | 279 |
| `frontend/src/components/dashboard/NavChart.jsx` | 271 |
| `frontend/src/hooks/useAdmin.js` | 260 |

---

## Remediation Plan (ordered by priority)

### Wave 1: Security (Effort: S, Impact: CRITICAL)
1. Replace `python-jose` with `PyJWT` — update `auth_service.py` encode/decode
2. Replace `passlib` with direct `bcrypt` — update `auth_service.py` hash/verify
3. Add `slowapi` rate limiter on `/api/auth/login` (5/min per IP)
4. Update `bcrypt` to 4.2.x, pin `yfinance<2.0`

### Wave 2: Test Foundation (Effort: M, Impact: CRITICAL)
5. Add `pytest`, `httpx`, `pytest-asyncio`, `factory-boy` to requirements.txt
6. Add `vitest`, `@testing-library/react`, `@testing-library/jest-dom` to package.json
7. Write tests for `risk_metrics.py` (pure functions, easiest to test, highest value)
8. Write tests for `auth_service.py` (security-critical)
9. Write tests for `xirr_service.py` (financial accuracy critical)
10. Write tests for `nav_parser.py` and `txn_parser.py` (data pipeline critical)

### Wave 3: Financial Code Safety (Effort: M, Impact: MAJOR)
11. Add `to_decimal()` conversion at risk_engine.py output boundary
12. Replace `_safe_float()` in txn_parser.py with `_safe_decimal()`
13. Fix cashflow_parser.py to parse amounts as Decimal
14. Audit all `float()` calls in portfolio.py and portfolio_detail.py routers

### Wave 4: File Splits (Effort: M, Impact: MAJOR)
15. Split `backend/routers/portfolio.py` (528 lines)
16. Split `backend/services/risk_metrics.py` (481 lines)
17. Split `backend/routers/portfolio_detail.py` (473 lines)
18. Split `frontend/src/app/dashboard/methodology/page.js` (536 lines)
19. Split `frontend/src/lib/methodology-sections.js` (450 lines)

### Wave 5: Error Handling + Type Safety (Effort: S-M, Impact: MINOR)
20. Fix silent exception swallowing in `holdings_service.py:35`
21. Add JSDoc type annotations to frontend hooks and lib files (incremental)

---

## What's Good (keep doing this)

- Clean `.gitignore` — `.env` not committed
- Config fails loudly on missing env vars (Pydantic Settings)
- Zero TODOs or dead code comments
- JIP design system consistently applied
- Indian number formatting properly implemented
- Single Dockerfile pattern correctly followed
- Error handling in ingestion pipeline is thorough (logs + continues)
- Decimal imports present in 20 files — foundation exists, just needs tightening
