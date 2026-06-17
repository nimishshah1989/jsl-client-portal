'use client';

import { useState, useEffect, useCallback } from 'react';
import { apiGet } from '@/lib/api';
import { buildPortfolioUrl, usePortfolioSelection } from '@/hooks/usePortfolioSelection';

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

// Each hook routes to the per-portfolio endpoint or the /combined/* variant
// based on the current dashboard selection (default COMBINED). `selection` is
// in the deps so a switch triggers a refetch.

export function useSummary() {
  const { selection } = usePortfolioSelection();
  return useApiData(buildPortfolioUrl('summary', selection), { selection });
}

/**
 * Per-sleeve snapshot + Combined total — powers the "Your Portfolios" glance
 * table on the Combined view. Always the combined-scoped endpoint (not routed
 * by selection); the component only shows it on the Combined view.
 */
export function usePortfoliosSummary() {
  return useApiData('/portfolio/combined/portfolios-summary');
}

export function useNavSeries(range = 'ALL') {
  const { selection } = usePortfolioSelection();
  return useApiData(buildPortfolioUrl('nav-series', selection, { range }), { selection, range });
}

export function usePerformanceTable() {
  const { selection } = usePortfolioSelection();
  return useApiData(buildPortfolioUrl('performance-table', selection), { selection });
}

export function useGrowth() {
  const { selection } = usePortfolioSelection();
  return useApiData(buildPortfolioUrl('growth', selection), { selection });
}

export function useAllocation() {
  const { selection } = usePortfolioSelection();
  return useApiData(buildPortfolioUrl('allocation', selection), { selection });
}

export function useHoldings(sort = 'weight', order = 'desc', assetClass = 'ALL') {
  const { selection } = usePortfolioSelection();
  const url = buildPortfolioUrl('holdings', selection, { sort, order, asset_class: assetClass });
  return useApiData(url, { selection, sort, order, assetClass });
}

export function useDrawdown(range = 'ALL') {
  const { selection } = usePortfolioSelection();
  return useApiData(buildPortfolioUrl('drawdown-series', selection, { range }), { selection, range });
}

export function useRiskScorecard() {
  const { selection } = usePortfolioSelection();
  return useApiData(buildPortfolioUrl('risk-scorecard', selection), { selection });
}

export function useTransactions(page = 1, perPage = 50, filters = {}) {
  const { selection } = usePortfolioSelection();
  const url = buildPortfolioUrl('transactions', selection, {
    page, per_page: perPage,
    txn_type: filters.txn_type, asset_class: filters.asset_class,
    date_from: filters.date_from, date_to: filters.date_to,
  });
  return useApiData(url, { selection, page, perPage, ...filters });
}

export function useXIRR() {
  const { selection } = usePortfolioSelection();
  return useApiData(buildPortfolioUrl('xirr', selection), { selection });
}

export function useMethodology() {
  const { selection } = usePortfolioSelection();
  return useApiData(buildPortfolioUrl('methodology', selection), { selection });
}
