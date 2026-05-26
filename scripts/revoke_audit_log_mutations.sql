-- =============================================================================
-- M7 — Audit-log integrity: revoke mutation grants on cpp_audit_log
-- =============================================================================
--
-- Purpose
--   SEBI compliance requires the audit trail (cpp_audit_log) to be append-only
--   at the database layer. The application's runtime role (`fie_admin`) only
--   needs INSERT and SELECT — never UPDATE, DELETE, or TRUNCATE. Even if the
--   app process is fully compromised, an attacker should not be able to
--   rewrite history through the existing DB connection.
--
-- How to apply (must be run MANUALLY by an operator after the PR is merged)
--
--   PGPASSWORD=<jip_admin_password> psql \
--     -h jip-data-engine.ctay2iewomaj.ap-south-1.rds.amazonaws.com \
--     -U jip_admin \
--     -d client_portal \
--     -f scripts/revoke_audit_log_mutations.sql
--
--   Run as `jip_admin` (or another superuser-equivalent role), NOT as
--   `fie_admin` itself — `fie_admin` cannot revoke its own privileges.
--
-- IMPORTANT — future migrations
--   Any future Alembic / manual migration that needs to UPDATE, DELETE, or
--   TRUNCATE rows in cpp_audit_log (e.g. a retention purge older than
--   7 years, a column rename that rewrites rows, schema rebuilds) MUST:
--     1. Connect as `jip_admin` (not as `fie_admin`), OR
--     2. Temporarily GRANT the needed privilege, perform the operation,
--        and then REVOKE it again — all within the same migration script.
--   Do NOT permanently re-grant UPDATE/DELETE/TRUNCATE on cpp_audit_log
--   to `fie_admin`.
-- =============================================================================

BEGIN;

-- 1. Revoke mutation rights on the audit table from the runtime app role.
REVOKE UPDATE, DELETE, TRUNCATE ON cpp_audit_log FROM fie_admin;

-- 2. Re-affirm the privileges the app actually needs (idempotent).
--    INSERT — to write new audit rows.
--    SELECT — to read audit history (admin views, compliance reports).
GRANT INSERT, SELECT ON cpp_audit_log TO fie_admin;

-- 3. The id column is a SERIAL backed by a sequence — INSERTs require
--    USAGE on that sequence. Re-grant explicitly so the lockdown above
--    doesn't accidentally break writes.
GRANT USAGE ON SEQUENCE cpp_audit_log_id_seq TO fie_admin;

COMMIT;

-- Verification (run manually after applying):
--   SELECT grantee, privilege_type
--     FROM information_schema.role_table_grants
--    WHERE table_name = 'cpp_audit_log' AND grantee = 'fie_admin';
-- Expected output: only INSERT and SELECT — no UPDATE, DELETE, or TRUNCATE.
