# Architecture Decisions Log
**Project:** JSL Client Portfolio Portal (CPP)
**Rule:** Append-only. Never edit or delete past decisions.

---

## ADR-001: Single Dockerfile Pattern (MF Pulse)
**Date:** 2026-03-18
**Status:** Accepted
**Context:** Need to deploy a Next.js frontend + FastAPI backend. Previous JIP modules used separate Vercel (frontend) + EC2 (backend) deployments which caused CORS issues and deployment complexity.
**Decision:** Bundle both Next.js and FastAPI in a single Docker container. Next.js proxies /api/* to FastAPI internally. Matches MF Pulse pattern.
**Consequences:** Zero CORS issues. Single deployment artifact. Trade-off: larger Docker image (~1GB), but deployment simplicity wins for a 1-person team.

---

## ADR-002: Existing RDS over Supabase
**Date:** 2026-03-18
**Status:** Accepted
**Context:** Database choice for client data. Supabase is used by some JIP modules, but the PMS backoffice data contains sensitive client financial information.
**Decision:** Use existing fie-db RDS instance with a new `client_portal` database. All tables use `cpp_` prefix. Direct SQLAlchemy access, no Supabase middleware.
**Consequences:** Full control over schema. No RLS overhead (we do scoping in application layer via JWT). Compatible with existing Market Pulse/MF Pulse data on same instance.

---

## ADR-003: Username/Password Auth over OTP
**Date:** 2026-03-18
**Status:** Accepted
**Context:** Need simple auth for ~200 PMS clients. Options: magic links, OTP (SMS/WhatsApp), username+password.
**Decision:** Username + password with bcrypt hashing and JWT in httpOnly cookies. Admin generates credentials in bulk.
**Consequences:** Zero external dependency (no SMS provider). Clients can change password. Trade-off: password reset flow needed. Can upgrade to OTP later (ADR recorded for future).

---

## ADR-004: Stateful Row-by-Row File Parsing
**Date:** 2026-03-18
**Status:** Accepted
**Context:** PMS backoffice exports are NOT flat CSVs. They have embedded client name headers, date separator rows, and merged column structures.
**Decision:** Build stateful parsers (nav_parser.py, txn_parser.py) that read row-by-row, tracking current_client and current_date as state. Use openpyxl read_only mode for memory efficiency on 35MB files.
**Consequences:** More complex parsing code, but handles the actual file format correctly. Column mapper approach from initial design replaced with fixed-position parsing based on known file structure.

---

## ADR-005: Server-Side Risk Computation with Storage
**Date:** 2026-03-18
**Status:** Accepted
**Context:** Risk metrics (Sharpe, Sortino, drawdowns, capture ratios) need to be computed for ~200 clients. Options: compute on-the-fly per API request, or pre-compute and store.
**Decision:** Pre-compute all metrics after every NAV upload. Store in cpp_risk_metrics table. Dashboard reads from stored values.
**Consequences:** Fast dashboard load (no computation on request). Trade-off: data is stale until next upload+recompute. Risk engine takes 2-5 mins for all 200 clients — acceptable since uploads are periodic (weekly/monthly).

---

<!-- Future decisions will be appended below by Claude during build sessions -->

## ADR-006: Production Readiness Remediation Backlog
**Date:** 2026-05-26
**Status:** Accepted — In Progress
**Context:** Pre-launch 4-agent audit (security under OWASP ASVS L2 + DPDP Act 2023, code/architecture, math accuracy, bug-hunt) identified 17 P0, 22 P1, 17+ P2, 13+ P3 issues. Verdict: not ready for 200-client launch.
**Decision:** Adopt a 4-sprint remediation plan tracked in `PRODUCTION_READINESS.md` (single source of truth, read at every session start). Sprint 1 (safety net) and Sprint 2 (math + accuracy) are blocking; Sprints 3 (DPDP rights) and 4 (quality) are pre-launch but lower urgency. Auth/cookie/JWT changes run sequentially due to overlapping files; math/test/quality streams run in parallel via worktree-isolated sub-agents.
**Consequences:** ~10–14 engineering days to defensible production. Each fix lands as its own PR gated by `/code-review` + `/security-review` + `/verify`. Pre-launch verification gate (12 manual checks against BJ53 reference data and Market Pulse) is non-negotiable.

---

## ADR-007: Multi-Portfolio per Person, Strategy Tagging & Combined View
**Date:** 2026-06-13
**Status:** Accepted — Combined view shipped; unified-login migration (PR7) pending.
**Context:** The PMS list is really 2+ strategy sleeves per person — a code ending `PASS` is Passive, `IND` is the IND11 strategy, else Leaders; `CLOSE`/`CLO` codes are archived. One human (e.g. Bhadresh = 6 codes) currently has 6 separate logins because each UCC is its own `cpp_clients` row. Operator wants: each portfolio tagged by strategy; an admin Leaders/Passive/IND11/Combined classification; and eventually one login per person seeing all their portfolios + a Combined default.
**Decision:**
1. Tag `cpp_portfolios` with `client_code`/`strategy`/`is_closed`; derivation is the single source of truth in `services/classification.py`, shared by backfill + ingestion. Closed excluded from all live/Combined views.
2. Combined view = sum of a person's **live** portfolios; ₹ quantities additive, returns/ratios recomputed from a combined TWR/composite (never summed). New `/api/portfolio/combined/*` endpoints, all client-scoped + reconciled (combined == sum of parts).
3. Group a person's codes by **exact full-name match** (interim; manual override map for spelling drift / same-name collisions).
4. Unified login (PR7): one login per person; **survivor = the code they already log in with**; retired logins aliased via `merged_into` (grace period); migration is transactional + reconciliation-before-commit, proven on a CI fixture, then staged behind an RDS snapshot. Ingestion switches to group-by-name only AFTER the migration runs.
5. CI: `tests.yml` runs `pytest` on every PR (added after finding two security suites silently red on main).
**Consequences:** Delivered as a stack (PR1–PR6 + CI/cleanup; PR7 pending — see `HANDOFF_MULTIPORTFOLIO.md`). Closed-account exclusion makes the admin "Total AUM" tick down by the 3 closed accounts vs before. Per-portfolio endpoints now accept `?portfolio_id=` (ownership-checked). Tenant-isolation matrix is the authoritative endpoint count (currently 23) — bump it when adding `/api/portfolio` GET endpoints.

---

## ADR-008: PR7a — Unified-Login Merge Migration (code only; execution gated)
**Date:** 2026-06-13
**Status:** Accepted — code merged; the data migration is NOT run until the gated execution path completes.
**Context:** Implementing the PR7 unified-login merge from ADR-007 §4. The migration re-parents a person's per-code clients onto one survivor. Three implementation realities forced concrete decisions.
**Decision:**
1. **Re-parent + rename.** Every portfolio is named `"PMS Equity"`, and `cpp_portfolios` has `UNIQUE(client_id, portfolio_name)`. Folding two onto one survivor would collide, so the migration renames re-parented portfolios to `"PMS Equity (<client_code>)"` — `client_code` is globally unique (`uq_cpp_portfolios_client_code`), so the result is collision-proof and the origin stays legible. Data-table re-parents only touch `client_id` (`portfolio_id` is unchanged, so their unique keys never collide).
2. **Reconcile-before-commit.** `merge_clients_by_name` does all writes through the caller's session and flushes but never commits; the CLI commits only after `verify_merge_invariants` passes (AUM/invested/current/portfolio-count invariant, cross-table ownership, dangling-portfolio refs, zero orphans, no merge chains). Any failure rolls back. The whole thing is engine-agnostic so the CI fixture runs the **real** migration on SQLite.
3. **Survivor pick is pure + active-first.** `pick_survivor` = (active beats disabled, then most-recent `last_login`, then lowest `id`) — the live code the person already uses.
4. **Auth alias denies, never strands.** A retired username resolves through `merged_into` (following multi-round chains, with a cycle guard) to the terminal survivor and lands there; if that unified account is unavailable, login is **denied** (403) rather than landing on the emptied retired account. Alias logins stamp the survivor's `last_login` and attribute the LOGIN audit to the survivor (with the alias recorded), so the trail and "last seen" stay correct.
5. **Audit is durable.** `cpp_merge_audit` FKs use NO delete action (not CASCADE) — the reversibility record must survive; the system soft-deletes clients anyway.
**Consequences:** PR7a is safe to merge but its SQL (`scripts/migrate_add_merge_columns.sql`) is additive and MUST be applied to prod **before** the code deploys (the ORM now maps `cpp_clients.merged_into`) — same operational ordering PR1 used. Execution stays gated: dry-run → RDS snapshot → staging restore + reconcile → prod. PR7b (ingestion group-by-name) only after the migration has run.

---

## ADR-009: Active/Inactive Portfolios, Combined Carry-Forward & Admin Strategy Table
**Date:** 2026-06-14
**Status:** Accepted — code merged (PRs #47–#50); dormant flagging + prod merge pending execution (see HANDOFF §0).
**Context:** The PR7 staging rehearsal surfaced two structural issues plus operator UX requests: (a) the combined view summed portfolios by shared NAV date, so a sleeve whose NAV ended earlier was dropped from the latest total (3/21 sampled clients under-counted); (b) **76 of 367 "live" portfolios** have stale NAV (dormant/redeemed accounts that dropped out of the daily NAV file but were never flagged) — they inflate AUM at stale values; (c) the operator wants live views to default to *current* money with an opt-in to include dormant, plus an at-a-glance metrics table.
**Decision:**
1. **Combined carry-forward.** `fetch_combined_nav_df` forward-fills each sleeve's last value to the union of dates before summing — the combined is additive across mismatched date ranges (a sleeve ending 2024 still contributes its last value; its line just ends in 2024). Carry-forward assumes the capital is still held; genuinely redeemed sleeves are excluded via `is_closed`.
2. **Active = latest NAV within `ACTIVE_WINDOW_DAYS` (30) of the firm's most recent NAV date.** Single source: `services/strategy_filter.active_cutoff/active_clause/active_params` (engine-portable; Python-computed cutoff, no Postgres `INTERVAL`). Admin aggregate + summary table + StatCards default to **active-only**; an **admin-only** "Include inactive portfolios" checkbox (`include_inactive`, default false) opts back in. Clients always see active-only via flagging (no firm-relative filter on the client dashboard — avoids blanking a laggy-but-live client's own view).
3. **Dormant → `is_closed`.** `scripts/flag_dormant_portfolios.py` flags live portfolios with stale NAV (> N days, default 90) OR no NAV at all (empty stubs like JA59) as `is_closed=true` (data retained, reversible). Operator confirmed: flag the redeemed dormant accounts; JA59's empty account → closed.
4. **Strategy Summary table** (admin landing): rows = Total AUM / CAGR / Deposits (30d) / Withdrawals (30d) / Max Drawdown; columns = Combined/Leaders/Passive/IND11. Total AUM is per-portfolio-latest; deposits & withdrawals are **separate** rolling-30-day sums from `cpp_cash_flows`.
5. **Benchmark = Nifty 50 for all strategies (interim).** Only Nifty 50 is stored; per-strategy indices deferred until the operator picks real ones.
**Consequences:** Live AUM will drop to the real figure once dormant accounts are flagged. `dashboard-analytics` still uses `DISTINCT ON (client_id)` — correct pre-merge but **must be rewritten per-portfolio before the prod merge** or unified-client StatCards undercount (the Strategy Summary table is already per-portfolio). Staging rehearsal baseline drifted from session-1's (`904,964,514.89 / 648,903,666.35` vs `905,234,707.58 / 651,769,759.97`) because prod data refreshed since 2026-06-12 — re-capture guard rails from a fresh dry-run each run.

---

## ADR-010: PR7 Prod Go-Live Executed (dashboard-analytics per-portfolio + dormant flagging + unified-login merge)
**Date:** 2026-06-14
**Status:** Accepted — **executed on prod**.
**Context:** Final cutover of the unified-login work (ADR-007/008/009). All gated steps were run on prod behind RDS snapshots, in the order mandated by `HANDOFF_MULTIPORTFOLIO.md §0`.
**Decision / what was done:**
1. **`dashboard-analytics` rewritten to per-portfolio aggregation (PR #52)** *before* the merge. Extracted the endpoint body from `backend/routers/admin.py` into `backend/services/admin_analytics.py::compute_dashboard_analytics`: each in-scope portfolio's own latest NAV/risk row via an **engine-portable CTE** (`MAX(nav_date)` then `MAX(id)` — no `DISTINCT ON`, so `tests/test_admin_analytics.py` runs the real query on SQLite); firm StatCards = Σ over all sleeves; blended CAGR/DD/Sharpe AUM-weighted per portfolio; **performer lists rolled up to one row per person** (the admin UI keys on `client_id`). Pre-merge output is identical (1 portfolio/client). Router is now a thin delegator; `admin.py` 591→398 lines.
2. **Dormant flagging executed** (`flag_dormant_portfolios.py --execute --days 90`): **80** live-but-stale/empty portfolios → `is_closed=true` (data retained, reversible). Live AUM ₹902,303,181 → **₹834,278,458** (−₹68.0M / 7.54%). Snapshot `fie-db-pre-dormant-flag-20260614`.
3. **Unified-login merge executed** (`merge_clients_by_name.py --execute`, guards `--expect-aum 904964514.89 --expect-invested 648903666.35`): **COMMITTED** with reconcile-before-commit; `verify_merge_invariants` confirmed AUM/invested/portfolio-count unchanged. **44** per-code clients retired across **36** people; **97,170** data rows re-parented onto survivors. Post-merge `validate_client_views.py --code BJ53` → BJ53 is one client owning 6 portfolios with `✓ invested == Σ live` (₹75.9L→₹1.13Cr); all multi-live-sleeve people reconcile. Credential delta: **44 retired logins, 0 ever used** → zero client disruption. Snapshot `fie-db-pre-merge-20260614`.
4. **In-portal Admin Guide** (`/admin/guide`) added so the firm's operators have a single reference for the strategy/active-dormant/combined/unified-login logic and the firm-level calculations.
**Consequences:** Unified login is live; retired usernames alias onto survivors via `merged_into`. Firm StatCards are now per-portfolio and correct under unified clients. A few large long-dormant accounts (KARAN ₹7.1M, MANHARLAL ₹5.0M, ASHESH-HUF ₹2.5M) now show ₹0 Combined (correct for redeemed; reversible if operator finds any still invested). Remaining: tear down `fie-db-staging` (keep the two `fie-db-pre-*` snapshots ~1 week), and **PR7b** (ingestion `find_or_create_client` by name) — the only feature still pending, now unblocked because the data migration has run.

