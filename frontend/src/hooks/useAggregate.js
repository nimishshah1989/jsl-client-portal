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

export function useAggregateNavSeries(range = 'ALL', strategy = 'COMBINED') {
  return useApiData(
    `/admin/aggregate/nav-series?range=${range}&strategy=${strategy}`,
    { range, strategy },
  );
}

export function useAggregatePerformance(strategy = 'COMBINED') {
  return useApiData(`/admin/aggregate/performance-table?strategy=${strategy}`, { strategy });
}

export function useAggregateRisk(strategy = 'COMBINED') {
  return useApiData(`/admin/aggregate/risk-scorecard?strategy=${strategy}`, { strategy });
}

export function useAggregateAllocation(strategy = 'COMBINED') {
  return useApiData(`/admin/aggregate/allocation?strategy=${strategy}`, { strategy });
}

export function useAggregateMonthlyReturns(strategy = 'COMBINED') {
  return useApiData(`/admin/aggregate/monthly-returns?strategy=${strategy}`, { strategy });
}
