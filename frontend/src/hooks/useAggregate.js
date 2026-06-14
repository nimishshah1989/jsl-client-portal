'use client';

import { useState, useEffect, useCallback } from 'react';
import { apiGet } from '@/lib/api';

/**
 * Generic data-fetching hook for aggregate admin endpoints.
 * Mirrors the pattern from usePortfolio.js.
 */
function useApiData(url, deps = {}) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const depsKey = JSON.stringify(deps);

  const refetch = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await apiGet(url);
      setData(result);
    } catch (err) {
      setError(err.message || 'Failed to fetch data');
    } finally {
      setLoading(false);
    }
  }, [url]);

  useEffect(() => {
    refetch();
  }, [refetch, depsKey]);

  return { data, loading, error, refetch };
}

export function useAggregateNavSeries(range = 'ALL', strategy = 'COMBINED', includeInactive = false) {
  return useApiData(
    `/admin/aggregate/nav-series?range=${range}&strategy=${strategy}&include_inactive=${includeInactive}`,
    { range, strategy, includeInactive },
  );
}

export function useAggregatePerformance(strategy = 'COMBINED', includeInactive = false) {
  return useApiData(
    `/admin/aggregate/performance-table?strategy=${strategy}&include_inactive=${includeInactive}`,
    { strategy, includeInactive },
  );
}

export function useAggregateRisk(strategy = 'COMBINED', includeInactive = false) {
  return useApiData(
    `/admin/aggregate/risk-scorecard?strategy=${strategy}&include_inactive=${includeInactive}`,
    { strategy, includeInactive },
  );
}

export function useAggregateAllocation(strategy = 'COMBINED', includeInactive = false) {
  return useApiData(
    `/admin/aggregate/allocation?strategy=${strategy}&include_inactive=${includeInactive}`,
    { strategy, includeInactive },
  );
}

export function useAggregateMonthlyReturns(strategy = 'COMBINED', includeInactive = false) {
  return useApiData(
    `/admin/aggregate/monthly-returns?strategy=${strategy}&include_inactive=${includeInactive}`,
    { strategy, includeInactive },
  );
}

export function useAggregateSummaryTable(includeInactive = false) {
  return useApiData(
    `/admin/aggregate/summary-table?include_inactive=${includeInactive}`,
    { includeInactive },
  );
}
