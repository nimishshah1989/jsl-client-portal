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

export function useAggregateNavSeries(range = 'ALL') {
  return useApiData(`/admin/aggregate/nav-series?range=${range}`, { range });
}

export function useAggregatePerformance() {
  return useApiData('/admin/aggregate/performance-table');
}

export function useAggregateRisk() {
  return useApiData('/admin/aggregate/risk-scorecard');
}

export function useAggregateAllocation() {
  return useApiData('/admin/aggregate/allocation');
}

export function useAggregateMonthlyReturns() {
  return useApiData('/admin/aggregate/monthly-returns');
}
