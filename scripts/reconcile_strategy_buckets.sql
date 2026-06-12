-- Reconciliation: strategy buckets must sum to the live aggregate. READ ONLY.
--
-- Proves the PR2 invariant: for the admin aggregate, Leaders + Passive + IND11
-- (live, closed excluded) == the Combined live total, every portfolio is
-- classified, and closed accounts are consistently excluded.
--
-- Run (EC2 box):
--   docker run --rm -i --network host -v "$PWD/scripts:/scripts" postgres:15 \
--     psql "$DBURL" -f /scripts/reconcile_strategy_buckets.sql
-- Contains no writes. Safe on production.

\pset pager off

\echo '=== 1. Portfolio counts by strategy x closed ==='
SELECT strategy, is_closed, count(*) AS portfolios
FROM cpp_portfolios
GROUP BY strategy, is_closed
ORDER BY strategy, is_closed;

\echo ''
\echo '=== 2. Any portfolio with an invalid strategy? (expect 0) ==='
SELECT count(*) AS invalid_strategy_rows
FROM cpp_portfolios
WHERE strategy NOT IN ('LEADERS', 'PASSIVE', 'IND11');

\echo ''
\echo '=== 3. Latest-date AUM: live total vs sum of strategy buckets (must match) ==='
\echo '(bucket_sum must equal live_total; closed_excluded is the archived AUM dropped)'
WITH latest AS (
    SELECT DISTINCT ON (n.portfolio_id)
        n.portfolio_id, n.nav_value, p.strategy, p.is_closed
    FROM cpp_nav_series n
    JOIN cpp_portfolios p ON p.id = n.portfolio_id
    JOIN cpp_clients c ON c.id = n.client_id
    WHERE c.is_active = true AND c.is_admin = false
    ORDER BY n.portfolio_id, n.nav_date DESC
)
SELECT
    round(sum(nav_value) FILTER (WHERE NOT is_closed), 2)                          AS live_total,
    round(sum(nav_value) FILTER (WHERE NOT is_closed AND strategy = 'LEADERS'), 2) AS leaders,
    round(sum(nav_value) FILTER (WHERE NOT is_closed AND strategy = 'PASSIVE'), 2) AS passive,
    round(sum(nav_value) FILTER (WHERE NOT is_closed AND strategy = 'IND11'), 2)   AS ind11,
    round(sum(nav_value) FILTER (WHERE NOT is_closed AND strategy IN ('LEADERS','PASSIVE','IND11')), 2) AS bucket_sum,
    round(coalesce(sum(nav_value) FILTER (WHERE is_closed), 0), 2)                 AS closed_excluded
FROM latest;

\echo ''
\echo '=== 4. Per-date reconciliation: dates where live total <> bucket sum (expect 0) ==='
WITH per_date AS (
    SELECT
        n.nav_date,
        sum(n.nav_value) FILTER (WHERE NOT p.is_closed) AS live_total,
        sum(n.nav_value) FILTER (
            WHERE NOT p.is_closed AND p.strategy IN ('LEADERS', 'PASSIVE', 'IND11')
        ) AS bucket_sum
    FROM cpp_nav_series n
    JOIN cpp_portfolios p ON p.id = n.portfolio_id
    JOIN cpp_clients c ON c.id = n.client_id
    WHERE c.is_active = true AND c.is_admin = false
    GROUP BY n.nav_date
)
SELECT count(*) AS mismatch_dates
FROM per_date
WHERE round(live_total, 2) <> round(coalesce(bucket_sum, 0), 2);

\echo ''
\echo '=== END ==='
