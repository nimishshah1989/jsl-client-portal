# Handoff — Multi‑Portfolio / Unified‑Login

**Last updated:** 2026-06-14 (session 2) · **Read this first when resuming this work in a new session.**

Goal: support one human client holding several PMS portfolios (codes), each tagged by **strategy** (Leaders / Passive / IND11) and a **closed** flag, with a **Combined** view, and eventually **one login per person** (all their portfolios + a Combined default).

---

## 0. RESUME HERE — prod go-live is DONE (2026-06-14, session 3)

**Unified login is LIVE on prod.** All three gated steps ran successfully behind RDS snapshots. Only **PR7b** (ingestion group-by-name) remains.

| Step | Status (2026-06-14) |
|------|---------------------|
| 1. `dashboard-analytics` → per-portfolio | ✅ **DONE** — PR **#52** merged + deployed. Extracted to `backend/services/admin_analytics.py::compute_dashboard_analytics` (engine-portable per-portfolio CTE, AUM-weighted blended metrics, per-person performer rollup). StatCards no longer undercount unified clients. `tests/test_admin_analytics.py` (6 tests; suite now 477). |
| 2. Flag dormant/empty portfolios | ✅ **DONE** — `flag_dormant_portfolios.py --execute --days 90` flagged **80** (76 stale + 4 empty stubs incl. JA59) `is_closed=true`. Live AUM ₹902,303,181 → **₹834,278,458** (−₹68,024,723, 7.54%). Snapshot `fie-db-pre-dormant-flag-20260614`. |
| 3. PR7 unified-login merge on PROD | ✅ **DONE** — `merge_clients_by_name.py --execute --expect-aum 904964514.89 --expect-invested 648903666.35`. **COMMITTED**, invariants held (AUM/invested/portfolio-count unchanged). 44 codes retired across 36 people; **97,170** data rows re-parented. `validate_client_views.py --code BJ53` → BJ53 = 1 client / 6 portfolios, `✓ invested == Σ live` (₹75.9L→₹1.13Cr). Credential delta: **44 retired logins, 0 ever used** (zero client disruption). Snapshot `fie-db-pre-merge-20260614`. |
| 4. Tear down `fie-db-staging` | ⏳ command handed to operator: `aws rds delete-db-instance --db-instance-identifier fie-db-staging --skip-final-snapshot --region ap-south-1`. **Keep both `fie-db-pre-*` snapshots** ~1 week as the rollback window. |
| 5. **PR7b** (the one remaining piece) | ⏳ **NOT STARTED.** Switch `find_or_create_client` to group-by-name + idempotency + new-client report + name-override map, so the *next* upload attaches new codes to the right person. Safe to build now (the merge has run). |

**Notes from the prod run (see L-013):**
- Dormant flagging (step 2) does **not** move the merge baseline — `capture_baseline` sums every NAV-bearing portfolio regardless of `is_closed` (so the AUM-invariant is robust). The dry-run reported AUM `904964514.89` / invested `648903666.35` (matched the staging guard rails exactly; prod hadn't drifted further). Re-capture from a fresh dry-run anyway.
- Flagging closed a few **large** long-dormant accounts (KARAN ₹7.1M, MANHARLAL ₹5.0M, ASHESH-HUF ₹2.5M); their Combined view now reads ₹0 (correct for redeemed; reversible un-close if any are still invested — **pending operator confirmation**).
- The merge credential CSV write failed inside the container (`Permission denied` on the host-mounted `scripts/`); by design it writes **after** commit so this can't roll back the merge — re-derive from `cpp_clients WHERE merged_into IS NOT NULL` (psql) or `cpp_merge_audit`.
- New in-portal **Admin Guide** page (`/admin/guide`, `frontend/src/app/admin/guide/page.js`) documents strategy / active-dormant / combined / unified-login logic + the firm-level calculations.

**Current prod state:** unified login active; `merged_into` aliases live; 80 dormant flagged closed; dashboard-analytics per-portfolio deployed. **Only PR7b is left.**

Scripts run from a throwaway container off the prod image pointed at the target DB:
```bash
ssh jprod && cd ~/apps/client-portal && git pull origin main
docker run --rm --network host --env-file $PWD/.env -v "$PWD/scripts:/app/scripts" \
  client-portal python /app/scripts/<script>.py [args]
```

---

## 1. Status

### Merged to `main` (all CI-gated by `tests.yml`; suite = 451 passing)
| PR | What |
|----|------|
| #32 | **PR1** schema: `cpp_portfolios.client_code` (unique) / `strategy` / `is_closed` + `classify_code()` + backfill. **Backfill RAN on prod** → 348 LEADERS / 15 PASSIVE / 4 IND11 / 3 CLOSED (367 total, reconciled). |
| #33 | **PR2** admin aggregate strategy toggle (Combined / Leaders / Passive / IND11); closed excluded. |
| #34 | **PR3** ingestion self‑tags portfolios in `find_or_create_portfolio` (+ post‑upload strategy tally). |
| #35 | **PR4** `resolve_portfolio(client_id, ?portfolio_id=)` with ownership check + `GET /portfolio/list`; **fixed a stale tenant‑isolation suite that was silently red on main.** |
| #36 | Restored a second silently‑red security suite (`test_impersonation`). |
| #37 | **CI**: `.github/workflows/tests.yml` runs `pytest` on every PR. |
| #38 | Removed obsolete `fix-nginx.yml` / `fix-data.yml` (red‑check noise). |
| #39–#43 | **PR5 / 5b / 5c / 5d / 5e** — combined‑view backend **COMPLETE**. Every dashboard section has a `/api/portfolio/combined/*` endpoint: summary, nav-series, holdings, risk-scorecard, performance-table, drawdown-series, allocation, growth, xirr, transactions, methodology. All reconciled (combined == sum of the client's **live** portfolios; closed excluded). Tenant‑isolation matrix = **23** endpoints, leak‑free. |

### Merged in session 2 (2026-06-14)
| PR | What |
|----|------|
| #44 | **PR6** dashboard portfolio switcher + Combined default — **merged** (was open at session-1 handoff). |
| #46 | **PR7a** unified-login merge migration: schema (`cpp_clients.merged_into` + `cpp_merge_audit`), `services/merge_service.py` (`pick_survivor`, `merge_clients_by_name`, `verify_merge_invariants`, `resolve_login_target`), `scripts/merge_clients_by_name.py`, auth alias, `scripts/PR7_STAGING_RUNBOOK.md`, `scripts/validate_client_views.py`, `tests/test_merge_service.py`. **Migration SQL applied to prod; code deployed dormant.** |
| #47 | Fix: logout now clears `impersonation_token` (a stale one wedged login → 200-then-401); combined summary returns `ytd_return` (YTD card was `--`). |
| #48 | Combined **carry-forward** (a dormant sleeve's last value stays in the combined total — fixes the 3 mismatched-date-range clients) + admin **active/inactive toggle** (default active-only; 30-day window) + **Strategy Summary table** (AUM/CAGR/Deposits-30d/Withdrawals-30d/MaxDD × Combined/Leaders/Passive/IND11). |
| #49 | `scripts/flag_dormant_portfolios.py` — flag dormant (stale-NAV) + empty live portfolios `is_closed=true`. **Merged but NOT run.** |
| #50 | Admin firm StatCards respect the active/inactive toggle (now match the Strategy Summary table). |

### Staging rehearsal result (2026-06-14, on a snapshot restore — prod untouched)
- The real merge ran on staging: **`verify_merge_invariants` passed** — AUM `904,964,514.89` / invested `648,903,666.35` **unchanged** before==after; 0 orphans; 0 ownership drift. 44 codes retired across 36 people (incl. Bhadresh's 6 → survivor BJ53). Credential CSV ≈ 44 retired logins, ~0 ever used.
- Post-merge `validate_client_views.py`: 17/21 sampled people reconciled immediately; the other 3 (JUHI/MAHENDRAKUMAR/MANHARLAL) were a **combined-view date-range bug → fixed by #48 carry-forward** (all reconcile now).
- Surfaced **76 of 367 "live" portfolios with stale NAV** (dormant/redeemed, up to 5 yrs) — handled by #49 (run pending). Benchmark per strategy = **Nifty 50 for all** for now (operator) → no chart change needed.

### Merged / executed in session 3 (2026-06-14) — PROD GO-LIVE
| PR / run | What |
|----------|------|
| #52 | **`dashboard-analytics` → per-portfolio** (`backend/services/admin_analytics.py`); admin StatCards stop undercounting unified clients post-merge. Suite → 477. |
| (prod run) | **Dormant flagging executed** — 80 portfolios `is_closed=true`; live AUM → ₹834,278,458. |
| (prod run) | **PR7 unified-login merge executed** — COMMITTED, invariants held; 44 retired / 0 ever used; BJ53 = 1 client / 6 portfolios reconciled. |
| (this PR) | **Admin Guide page** (`/admin/guide`) + docs updated to reflect go-live. |

### NOT yet done
- Tear down `fie-db-staging` (operator) · confirm large flagged-dormant accounts are redeemed · **PR7b ingestion-by-name** (the only remaining feature).

---

## 2. Locked decisions (confirmed with the operator)
- **Strategy from code suffix:** ends `PASS` → PASSIVE; ends `IND` → IND11; ends `CLOSE`/`CLO` → `is_closed`; else LEADERS. Single source of truth: `backend/services/classification.py` (33 tests). Used by both the backfill and ongoing ingestion.
- **Closed** accounts: data retained, **excluded** from all live aggregates and Combined.
- **Grouping a person's codes:** by **exact full‑name match** (interim). Caveat: spelling drift (the file shows e.g. "BHADERESH JITENDRA JHAVERI") won't group → needs a small **manual name‑override map** for exceptions. Two distinct people with an identical full name would wrongly merge — review the pre‑flight collision report.
- **Unified login:** one login per person; **survivor = the code they already log in with**; retired logins kept as **aliases** (grace period, `merged_into`); **Combined is the default landing view**.

## 3. Pre‑flight numbers (ran on prod 2026‑06‑12 via `scripts/preflight_merge_report.sql`)
- 367 codes/clients → **323 people**. **287 single‑code** (untouched). **36 multi‑code groups** → 80 codes collapse, **44 retired**.
- **0 of the 44 retired logins were ever used** → near‑zero credential disruption.
- Baseline (must be invariant post‑migration): **total AUM `905234707.58`**, **invested `651769759.97`**, **0 cross‑table ownership mismatches**.
- Bhadresh has 6 codes (BJ53 + BJ53AML/IND/MF/NEW/PASS); survivor = **BJ53** (only one with a `last_login`). Jeet / Yash are separate names (correctly not merged).

---

## 4. PR7 — the safest path (build → prove in CI → stage → snapshot → prod)

**Principle:** make the migration provably correct on a controlled fixture *before* it touches prod; then run it behind reversible gates.

### PR7a (safe to merge — changes nothing until the script is run)
- **Schema** (`scripts/migrate_add_merge_columns.sql`): `cpp_clients.merged_into INTEGER NULL → cpp_clients(id)`; `cpp_merge_audit` table (survivor_id, retired_id, retired_code, retired_username, ran_at, reverted_at).
- **`backend/services/merge_service.py`**:
  - `pick_survivor(members)` — pure: most recent `last_login`, else lowest `id`. Unit‑test it.
  - `merge_clients_by_name(db, dry_run=True)` — group non‑admin/non‑deleted clients by name; for each multi‑code group re‑parent the non‑survivors' **portfolios + every data table's `client_id`** (`cpp_nav_series`, `cpp_transactions`, `cpp_holdings`, `cpp_risk_metrics`, `cpp_drawdown_series`, `cpp_cash_flows`) to the survivor; soft‑retire non‑survivors (`merged_into`, keep `is_active` for alias grace); write `cpp_merge_audit`. **One transaction.**
  - `verify_merge_invariants(db, baseline)` — assert: total AUM unchanged; portfolio count unchanged; every data row's `client_id` == its portfolio's `client_id` (0 drift); 0 rows owned by a `merged_into` client (orphans); each survivor owns only codes sharing its name. **Run before commit; abort+rollback on any failure.**
- **Auth alias**: in the login path (`backend/routers/auth.py`), after resolving the username's client, if `merged_into` is set, issue the JWT for the **survivor** (retired username lands on the survivor's account).
- **`scripts/merge_clients_by_name.py`**: CLI wrapper, `--dry-run` default (read‑only report), real run is transactional and only commits if `verify_merge_invariants` passes.
- **`tests/test_merge_service.py`** — THE rigor: seed a production‑shaped mini‑DB (multi‑code person + single‑code person + closed account + rows in every table), capture baseline, run the real migration on it, assert every invariant + alias‑login resolves to survivor. Runs in CI.

### Execution (gated — needs operator + AWS; do NOT skip)
1. `--dry-run` on prod (read‑only) → review the merge report.
2. **RDS snapshot.**
3. Restore snapshot → **staging DB** → run the real migration there → `verify_merge_invariants` green → spot‑check a merged login.
4. Prod run (transactional, recon‑before‑commit) → emit the credential‑delta CSV (≈0 active).
5. **PR7b (only AFTER the migration has run):** switch `find_or_create_client` to key on **name** (so future uploads attach codes to the person), + an idempotency check (re‑parse latest files → maps to the same structure), + a "new clients created this upload" review report, + the manual name‑override map. Ordering is critical: never deploy ingestion‑by‑name before the data is migrated.

---

## 5. How to resume (new session)

**Run the test suite** (deps are not preinstalled in agent sessions):
```bash
pip install fastapi "sqlalchemy[asyncio]" aiosqlite httpx pydantic pydantic-settings \
  python-jose passlib bcrypt cffi numpy pandas scipy asyncpg psycopg2-binary \
  yfinance openpyxl tenacity python-dotenv pytest pytest-asyncio
DATABASE_URL='postgresql+asyncpg://test:test@localhost/test' \
  JWT_SECRET='ci-only-test-secret-0123456789abcdef0123456789abcdef' \
  pytest -q          # expect: 451 passed (more once PR7a lands)
```
(CI already does this on every PR via `tests.yml`.)

**Reach the prod DB** (not wired into agent sessions): either set the `INFRA_ACCESS.md` env vars (`EC2_HOST`, `SSH_PRIVATE_KEY`, `RDS_MASTER_USER`, `RDS_MASTER_PW`) to tunnel via EC2, **or** run scripts on the box directly:
```bash
ssh ubuntu@13.206.34.214            # clients.jslwealth.in
cd ~/apps/client-portal && git pull origin main
DBURL=$(grep -E '^DATABASE_URL_SYNC=' .env | head -1 | cut -d= -f2- | sed -E 's/^["'"'"']//; s/["'"'"']$//')
docker run --rm -i --network host -v "$PWD/scripts:/scripts" postgres:15 psql "$DBURL" -f /scripts/<file>.sql
```

**Key files:** `services/classification.py`, `services/strategy_filter.py`, `services/combined_service.py`, `services/combined_analytics.py`, `routers/portfolio_combined.py`, `routers/helpers.py` (`resolve_portfolio`), `scripts/preflight_merge_report.sql`, `scripts/reconcile_strategy_buckets.sql`, `tests/test_tenant_isolation.py` (endpoint matrix = 23, bump when adding endpoints).

**Tooling:** `gstack` + `superpowers` skills were installed into `~/.claude/skills/` (ephemeral — reinstall in a fresh session if wanted: gstack via `git clone … ~/.claude/skills/gstack && ./setup`; superpowers via `/plugin install superpowers@claude-plugins-official`).

---

## 6. PR7 build checklist
- [x] PR7a schema migration SQL + model column (`Client.merged_into`) — `scripts/migrate_add_merge_columns.sql` + `cpp_merge_audit` (`models/merge_audit.py`). **Additive; apply to prod BEFORE deploying PR7a code (ORM now maps `merged_into`) — same ordering as PR1.**
- [x] `merge_service.py` (`pick_survivor` [active‑first], `capture_baseline`, `merge_clients_by_name`, `verify_merge_invariants`, `resolve_login_target`)
- [x] `scripts/merge_clients_by_name.py` (`--dry-run` default, transactional, recon‑before‑commit, `--expect-aum/--expect-invested` guards, credential CSV after commit)
- [x] auth alias (login resolves `merged_into` → survivor, follows chains, denies if unified acct unavailable; stamps survivor `last_login`; audits under survivor)
- [x] `tests/test_merge_service.py` (seeded prod‑shaped DB: multi‑code + single‑code + closed + admin + soft‑deleted‑same‑name; runs the REAL migration; asserts every invariant + alias resolution + idempotency + chain/cycle; **in CI**). Suite **471 passing** (session 2).
- [x] STAGING rehearsal done (snapshot → restore → migrate → merge → validate → all green; carry-forward fix #48). prod untouched.
- [x] (polish) PR6 follow-ups: combined summary `ytd_return` (#47); active/inactive toggle + Strategy Summary table (#48); StatCards toggle (#50). Combined holdings cash-breakdown rows still deferred.
- [x] **`dashboard-analytics` per-portfolio rewrite** — PR **#52** (`backend/services/admin_analytics.py`), merged + deployed 2026-06-14.
- [x] **Ran `flag_dormant_portfolios.py` on prod** — flagged 80 (`is_closed=true`); live AUM → ₹834,278,458. Snapshot `fie-db-pre-dormant-flag-20260614`.
- [x] **Ran PR7 merge on PROD** — COMMITTED, invariants held; 44 retired / 0 ever used; BJ53 reconciles. Snapshot `fie-db-pre-merge-20260614`.
- [x] In-portal **Admin Guide** page (`/admin/guide`) documenting the logic + calculations.
- [ ] Tear down `fie-db-staging` (command handed to operator; keep `fie-db-pre-*` snapshots ~1 week).
- [ ] Confirm the large flagged-dormant accounts (KARAN/MANHARLAL/ASHESH) are genuinely redeemed (reversible un-close otherwise).
- [ ] **PR7b**: ingestion `find_or_create_client` by name (post-migration) + idempotency + new-client report + name-override map.
