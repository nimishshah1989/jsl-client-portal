'use client';

import { createContext, useCallback, useContext, useEffect, useState } from 'react';
import { apiGet } from '@/lib/api';

/**
 * Portfolio selection context for the dashboard.
 *
 * `selection` is either the string 'COMBINED' (default — aggregates the
 * client's live portfolios) or a numeric portfolio_id. The data hooks in
 * usePortfolio.js read this to route each request to either the per-portfolio
 * endpoint (`?portfolio_id=`) or the `/portfolio/combined/*` variant.
 */
const SelectionContext = createContext(null);

/**
 * Build the API URL for a portfolio section given the current selection.
 * COMBINED -> /portfolio/combined/<section>; a portfolio_id -> the
 * per-portfolio endpoint scoped with ?portfolio_id=. Empty / 'ALL' params are
 * dropped (both backends default range/asset_class to ALL).
 */
export function buildPortfolioUrl(section, selection, params = {}) {
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && v !== '' && v !== 'ALL') {
      qs.set(k, String(v));
    }
  }
  if (selection === 'COMBINED' || selection == null) {
    const q = qs.toString();
    return `/portfolio/combined/${section}${q ? `?${q}` : ''}`;
  }
  qs.set('portfolio_id', String(selection));
  return `/portfolio/${section}?${qs.toString()}`;
}

export function PortfolioSelectionProvider({ children }) {
  const [selection, setSelection] = useState('COMBINED');
  const [portfolios, setPortfolios] = useState([]);

  const load = useCallback(async () => {
    try {
      const list = await apiGet('/portfolio/list');
      setPortfolios(Array.isArray(list) ? list : []);
    } catch {
      setPortfolios([]);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <SelectionContext.Provider value={{ selection, setSelection, portfolios }}>
      {children}
    </SelectionContext.Provider>
  );
}

/**
 * Returns { selection, setSelection, portfolios }. Falls back to a COMBINED
 * default when used outside the provider so hooks never crash.
 */
export function usePortfolioSelection() {
  return (
    useContext(SelectionContext) ||
    { selection: 'COMBINED', setSelection: () => {}, portfolios: [] }
  );
}
