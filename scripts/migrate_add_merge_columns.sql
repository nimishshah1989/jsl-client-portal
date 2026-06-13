-- Migration: unified-login merge support (PR7a).
--
-- Adds the soft-retire pointer on clients and the merge audit trail. This is
-- ADDITIVE + IDEMPOTENT and changes NO behaviour on its own: merged_into is NULL
-- for every existing client, and cpp_merge_audit starts empty. Nothing is merged
-- until scripts/merge_clients_by_name.py --execute is run (gated behind a dry-run,
-- an RDS snapshot, and a staging rehearsal).
--
-- IMPORTANT (deploy ordering): apply this SQL to prod BEFORE deploying the PR7a
-- code, because backend/models/client.py now maps the merged_into column and the
-- ORM SELECTs it on every client load (login, /me, etc.). It runs in milliseconds.
--
-- Rule for who merges whom lives in backend/services/merge_service.py
-- (pick_survivor / merge_clients_by_name); this file only provisions the schema.

-- ── 1. Soft-retire pointer on cpp_clients ──
-- Non-survivors point at their survivor's id. is_active is intentionally NOT
-- changed by the merge, so retired usernames keep working during the alias
-- grace period (login resolves merged_into -> survivor and issues the survivor's
-- JWT). ON DELETE SET NULL mirrors the existing deleted_by self-reference.
ALTER TABLE cpp_clients
    ADD COLUMN IF NOT EXISTS merged_into INTEGER NULL
        REFERENCES cpp_clients(id) ON DELETE SET NULL;

COMMENT ON COLUMN cpp_clients.merged_into IS
    'PR7 unified-login: survivor client id this (retired) client was folded into; NULL = not merged';

-- Partial index — only retired rows carry a value, so this stays tiny.
CREATE INDEX IF NOT EXISTS ix_cpp_clients_merged_into
    ON cpp_clients (merged_into)
    WHERE merged_into IS NOT NULL;

-- ── 2. Merge audit trail (reversibility record) ──
-- One row per retired->survivor fold. reverted_at is stamped if a merge is undone.
-- The FKs deliberately have NO ON DELETE action: this is the reversibility record
-- and must survive — a referenced client cannot be hard-deleted without first
-- handling its audit rows (the system soft-deletes clients anyway). The
-- denormalised retired_code/username/name keep the row human-readable regardless.
CREATE TABLE IF NOT EXISTS cpp_merge_audit (
    id               SERIAL PRIMARY KEY,
    survivor_id      INTEGER NOT NULL REFERENCES cpp_clients(id),
    retired_id       INTEGER NOT NULL REFERENCES cpp_clients(id),
    retired_code     VARCHAR(50),
    retired_username VARCHAR(100),
    name             VARCHAR(200),
    ran_at           TIMESTAMP NOT NULL DEFAULT now(),
    reverted_at      TIMESTAMP NULL
);

COMMENT ON TABLE cpp_merge_audit IS
    'PR7 unified-login: audit trail of retired->survivor client merges (reversibility record)';

CREATE INDEX IF NOT EXISTS ix_cpp_merge_audit_survivor ON cpp_merge_audit (survivor_id);
CREATE INDEX IF NOT EXISTS ix_cpp_merge_audit_retired  ON cpp_merge_audit (retired_id);
