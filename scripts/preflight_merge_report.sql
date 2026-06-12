-- ============================================================================
-- Pre-flight MERGE report — READ ONLY (pure SELECTs, writes nothing)
-- ============================================================================
-- Purpose: quantify the blast radius of merging per-code clients into
-- per-person clients (grouped by EXACT full name), ahead of the unified-login
-- migration. Strategy rule: client_code ending in 'PASS' = PASSIVE, else LEADERS.
--
-- How to run (on the EC2 box, which can reach RDS), using the app's own creds:
--   docker exec -i client-portal sh -lc \
--     'psql "$DATABASE_URL_SYNC" -f -' < scripts/preflight_merge_report.sql
-- or via an SSH tunnel from your laptop:
--   psql -h 127.0.0.1 -p 15432 -U "$RDS_MASTER_USER" -d client_portal \
--     -f scripts/preflight_merge_report.sql
--
-- SAFETY: contains no INSERT/UPDATE/DELETE/DDL. Safe to run on production.
-- Optional belt-and-suspenders: wrap in a read-only tx by running first:
--   SET default_transaction_read_only = on;
-- ============================================================================

\pset pager off
\echo '================ 1. TOTALS (non-admin, not deleted) ================'
SELECT
  (SELECT count(*) FROM cpp_clients   WHERE is_deleted = false AND is_admin = false) AS clients_total,
  (SELECT count(*) FROM cpp_portfolios)                                              AS portfolios_total;

\echo ''
\echo '================ 2. STRATEGY TALLY (by code suffix) ================'
SELECT
  CASE WHEN upper(client_code) LIKE '%PASS' THEN 'PASSIVE' ELSE 'LEADERS' END AS strategy,
  count(*) AS clients
FROM cpp_clients
WHERE is_deleted = false AND is_admin = false
GROUP BY 1
ORDER BY 1;

\echo ''
\echo '================ 3. BLAST RADIUS (people = distinct full name) ================'
WITH g AS (
  SELECT name, count(*) AS code_count
  FROM cpp_clients
  WHERE is_deleted = false AND is_admin = false
  GROUP BY name
)
SELECT
  count(*)                              AS people_total,
  count(*) FILTER (WHERE code_count = 1) AS people_single_code,
  count(*) FILTER (WHERE code_count > 1) AS people_multi_code,
  coalesce(sum(code_count) FILTER (WHERE code_count > 1), 0) AS codes_inside_multi_groups
FROM g;

\echo ''
\echo '================ 4. MULTI-CODE GROUPS (merge candidates) ================'
SELECT
  name,
  count(*) AS code_count,
  string_agg(client_code, ', ' ORDER BY client_code) AS codes
FROM cpp_clients
WHERE is_deleted = false AND is_admin = false
GROUP BY name
HAVING count(*) > 1
ORDER BY count(*) DESC, name;

\echo ''
\echo '================ 5. PER-CODE DETAIL for multi-code people ================'
\echo '(survivor = the row with the most recent last_login; others get retired+aliased)'
WITH multi AS (
  SELECT name FROM cpp_clients
  WHERE is_deleted = false AND is_admin = false
  GROUP BY name HAVING count(*) > 1
)
SELECT
  c.name,
  c.client_code,
  c.username,
  CASE WHEN upper(c.client_code) LIKE '%PASS' THEN 'PASSIVE' ELSE 'LEADERS' END AS strategy,
  c.is_active,
  c.last_login,
  row_number() OVER (PARTITION BY c.name ORDER BY c.last_login DESC NULLS LAST, c.id) AS proposed_rank
FROM cpp_clients c
JOIN multi m ON m.name = c.name
WHERE c.is_deleted = false AND c.is_admin = false
ORDER BY c.name, proposed_rank;

\echo ''
\echo '================ 6. CREDENTIAL DELTA (logins that would be retired) ================'
WITH multi AS (
  SELECT name FROM cpp_clients
  WHERE is_deleted = false AND is_admin = false
  GROUP BY name HAVING count(*) > 1
),
ranked AS (
  SELECT c.*,
         row_number() OVER (PARTITION BY c.name ORDER BY c.last_login DESC NULLS LAST, c.id) AS rn
  FROM cpp_clients c
  JOIN multi m ON m.name = c.name
  WHERE c.is_deleted = false AND c.is_admin = false
)
SELECT
  count(*) FILTER (WHERE rn > 1)                              AS codes_to_retire,
  count(*) FILTER (WHERE rn > 1 AND last_login IS NOT NULL)   AS retired_logins_already_active,
  count(*) FILTER (WHERE rn = 1 AND last_login IS NULL)       AS survivors_never_logged_in
FROM ranked;

\echo ''
\echo '================ 7. DATA ROWS TO RE-PARENT (sizing the migration) ================'
\echo '(rows currently owned by a non-survivor client_id that would move to the survivor)'
WITH multi AS (
  SELECT name FROM cpp_clients
  WHERE is_deleted = false AND is_admin = false
  GROUP BY name HAVING count(*) > 1
),
ranked AS (
  SELECT c.id, c.name,
         row_number() OVER (PARTITION BY c.name ORDER BY c.last_login DESC NULLS LAST, c.id) AS rn
  FROM cpp_clients c
  JOIN multi m ON m.name = c.name
  WHERE c.is_deleted = false AND c.is_admin = false
),
nonsurv AS (SELECT id FROM ranked WHERE rn > 1)
SELECT
  (SELECT count(*) FROM cpp_nav_series      n  WHERE n.client_id  IN (SELECT id FROM nonsurv)) AS nav_rows,
  (SELECT count(*) FROM cpp_transactions    t  WHERE t.client_id  IN (SELECT id FROM nonsurv)) AS txn_rows,
  (SELECT count(*) FROM cpp_holdings        h  WHERE h.client_id  IN (SELECT id FROM nonsurv)) AS holding_rows,
  (SELECT count(*) FROM cpp_risk_metrics    r  WHERE r.client_id  IN (SELECT id FROM nonsurv)) AS risk_rows,
  (SELECT count(*) FROM cpp_drawdown_series d  WHERE d.client_id  IN (SELECT id FROM nonsurv)) AS drawdown_rows,
  (SELECT count(*) FROM cpp_portfolios      p  WHERE p.client_id  IN (SELECT id FROM nonsurv)) AS portfolios_to_reparent;

\echo ''
\echo '================ 8. CROSS-TABLE CONSISTENCY BASELINE (pre-migration) ================'
\echo '(every data row should already have client_id == its portfolio owner; expect 0 mismatches)'
SELECT
  (SELECT count(*) FROM cpp_nav_series   n JOIN cpp_portfolios p ON p.id = n.portfolio_id WHERE n.client_id <> p.client_id) AS nav_owner_mismatch,
  (SELECT count(*) FROM cpp_transactions t JOIN cpp_portfolios p ON p.id = t.portfolio_id WHERE t.client_id <> p.client_id) AS txn_owner_mismatch,
  (SELECT count(*) FROM cpp_holdings     h JOIN cpp_portfolios p ON p.id = h.portfolio_id WHERE h.client_id <> p.client_id) AS holding_owner_mismatch;

\echo ''
\echo '================ 9. FIRM-WIDE AUM BASELINE (must be invariant after migration) ================'
\echo '(latest nav_value per portfolio, summed — re-run post-migration and compare)'
WITH latest AS (
  SELECT DISTINCT ON (portfolio_id) portfolio_id, nav_value, invested_amount, current_value
  FROM cpp_nav_series
  ORDER BY portfolio_id, nav_date DESC
)
SELECT
  count(*)                       AS portfolios_with_nav,
  round(sum(nav_value), 2)       AS total_aum,
  round(sum(invested_amount), 2) AS total_invested,
  round(sum(current_value), 2)   AS total_current_value
FROM latest;

\echo ''
\echo '================ 10. NAME-COLLISION CAUTION ================'
\echo '(multi-code groups where the codes do NOT share a common base after stripping a trailing PASS —'
\echo ' review these by eye: could be one person with unrelated accounts, or two different people same name)'
WITH multi AS (
  SELECT name FROM cpp_clients
  WHERE is_deleted = false AND is_admin = false
  GROUP BY name HAVING count(*) > 1
),
bases AS (
  SELECT c.name,
         regexp_replace(upper(c.client_code), 'PASS$', '') AS base_code
  FROM cpp_clients c
  JOIN multi m ON m.name = c.name
  WHERE c.is_deleted = false AND c.is_admin = false
)
SELECT name,
       count(DISTINCT base_code) AS distinct_base_codes,
       string_agg(DISTINCT base_code, ', ' ORDER BY base_code) AS base_codes
FROM bases
GROUP BY name
HAVING count(DISTINCT base_code) > 1
ORDER BY count(DISTINCT base_code) DESC, name;

\echo ''
\echo '================ END OF REPORT ================'
