'use client';

import { useState, useEffect, useCallback } from 'react';
import { apiGet } from '@/lib/api';

/**
 * Generic data-fetching hook with loading/error state.
 * @param {string} url — API endpoint (appended to /api by apiGet)
 * @param {object} deps — dependency values that trigger refetch
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

export function useSummary() {
  return useApiData('/portfolio/summary');
}

export function useNavSeries(range = 'ALL') {
  return useApiData(`/portfolio/nav-series?range=${range}`, { range });
}

export function usePerformanceTable() {
  return useApiData('/portfolio/performance-table');
}

export function useGrowth() {
  return useApiData('/portfolio/growth');
}

export function useAllocation() {
  return useApiData('/portfolio/allocation');
}

export function useHoldings(sort = 'weight', order = 'desc', assetClass = 'ALL') {
  const params = new URLSearchParams({ sort, order });
  if (assetClass && assetClass !== 'ALL') {
    params.set('asset_class', assetClass);
  }
  return useApiData(`/portfolio/holdings?${params.toString()}`, { sort, order, assetClass });
}

export function useDrawdown(range = 'ALL') {
  return useApiData(`/portfolio/drawdown-series?range=${range}`, { range });
}

export function useRiskScorecard() {
  return useApiData('/portfolio/risk-scorecard');
}

export function useTransactions(page = 1, perPage = 50, filters = {}) {
  const params = new URLSearchParams({ page: String(page), per_page: String(perPage) });
  if (filters.txn_type) params.set('txn_type', filters.txn_type);
  if (filters.asset_class) params.set('asset_class', filters.asset_class);
  if (filters.date_from) params.set('date_from', filters.date_from);
  if (filters.date_to) params.set('date_to', filters.date_to);
  return useApiData(`/portfolio/transactions?${params.toString()}`, { page, perPage, ...filters });
}

export function useXIRR() {
  return useApiData('/portfolio/xirr');
}

export function useMethodology() {
  return useApiData('/portfolio/methodology');
}
