'use client';

import { useState, useEffect } from 'react';
import { apiFetch } from '@/lib/api';
import { useSummary } from '@/hooks/usePortfolio';
import { formatDate } from '@/lib/format';
import { Download } from 'lucide-react';
import Button from '@/components/ui/Button';

/**
 * Client header: welcome message, portfolio name, as-of date, download button.
 * Fetches user profile directly from /auth/me to display the client name.
 */
export default function ClientHeader() {
  const [user, setUser] = useState(null);
  const { data: summary } = useSummary();

  useEffect(() => {
    async function fetchUser() {
      try {
        const data = await apiFetch('/auth/me');
        setUser(data);
      } catch {
        // Auth failure handled by dashboard layout redirect
      }
    }
    fetchUser();
  }, []);

  const clientName = user?.name || user?.client_name || 'Client';
  const portfolioName = user?.portfolio_name || 'PMS Equity';
  const asOfDate = summary?.as_of_date ? formatDate(summary.as_of_date) : '--';

  return (
    <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
      <div>
        <h1 className="text-2xl font-bold text-slate-800">
          Welcome, {clientName}
        </h1>
        <p className="text-sm text-slate-500 mt-1">
          {portfolioName} &middot; Data as of {asOfDate}
        </p>
      </div>
      <Button
        variant="secondary"
        size="sm"
        onClick={() => {
          // PDF download will be implemented in future
          alert('PDF report download coming soon.');
        }}
      >
        <Download className="w-4 h-4" />
        Download Report
      </Button>
    </div>
  );
}
