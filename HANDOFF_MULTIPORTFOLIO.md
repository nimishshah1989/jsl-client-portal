# Handoff — Multi‑Portfolio / Unified‑Login

**Last updated:** 2026-06-13 · **Read this first when resuming this work in a new session.**

Goal: support one human client holding several PMS portfolios (codes), each tagged by **strategy** (Leaders / Passive / IND11) and a **closed** flag, with a **Combined** view, and eventually **one login per person** (all their portfolios + a Combined default).

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

### Open / in review
- **PR6 (#44)** — dashboard **portfolio switcher + Combined default** (frontend). NOT yet merged. Needs an `npm run build` + visual pass on staging (no `node_modules` in agent sessions). Minor polish deferred: combined summary lacks `ytd_return`/benchmark fields (cards show `--`); combined holdings is a flat list without the cash‑breakdown rows PR1 added (footer falls back to the holdings sum).

### NOT started
- **PR7** — the unified‑login **merge migration** (the high‑risk, prod‑data piece). This handoff exists to start it cleanly.

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
- [x] `tests/test_merge_service.py` (seeded prod‑shaped DB: multi‑code + single‑code + closed + admin + soft‑deleted‑same‑name; runs the REAL migration; asserts every invariant + alias resolution + idempotency + chain/cycle; **in CI**). Suite now **465 passing**.
- [ ] EXECUTION (operator + AWS): follow **`scripts/PR7_STAGING_RUNBOOK.md`** — snapshot → restore to staging → migrate → merge → re-run `validate_client_views.py` (proves combined == Σ parts) → spot-check alias login → teardown; then repeat on prod. Guard rails `--expect-aum 905234707.58 --expect-invested 651769759.97`.
- [ ] PRE-REQ data fixes surfaced by `validate_client_views.py --code BJ53 --sample 20` (2026-06-13): **JA59/JAYASREE** live account empty (data trapped in closed `JA59CLOSE`) → Combined reads ₹0; confirm the 5 NAV-only `*AML`/`JFC` accounts are intentionally cash/no-trades. Holdings logic itself validated clean (0 compute bugs across 21 people).
- [ ] PR7b: ingestion `find_or_create_client` by name (post‑migration) + idempotency + new‑client report + name‑override map
- [ ] (polish) PR6 follow‑ups: combined summary `ytd_return`/benchmark fields; combined holdings cash‑breakdown rows
