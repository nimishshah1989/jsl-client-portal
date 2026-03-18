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
