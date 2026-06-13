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

