'use client';

import { useEffect, useState } from 'react';
import { Info } from 'lucide-react';
import { apiFetch } from '@/lib/api';
import { formatDate } from '@/lib/format';

/**
 * C11: Reconciliation status banner — SOFT GATE.
 *
 * Fetches /auth/me and renders a yellow advisory banner only when the
 * backend explicitly reports `is_recon_clean === false`. NULL / undefined /
 * true → no banner (defensive default for clients with no recon history).
 *
 * The banner never blocks rendering of any data below it. Dashboard renders
 * normally; this is purely a visual heads-up.
 *
 * JIP design tokens: amber-50 / amber-200 / amber-800 (never red).
 */
export default function ReconStatusBanner() {
  const [user, setUser] = useState(null);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const data = await apiFetch('/auth/me');
        if (!cancelled) setUser(data);
      } catch {
        // Auth handled by layout — silently no-op here.
      }
    }
    load();
    return () => {
      cancelled = true;
    };
  }, []);

  // Strict equality check — only show banner when backend explicitly says false.
  if (!user || user.is_recon_clean !== false) {
    return null;
  }

  const runAt = user.recon_last_run_at
    ? formatDate(user.recon_last_run_at)
    : 'a recent date';
  const notes = user.recon_notes || null;

  return (
    <div
      role="status"
      className="bg-amber-50 border border-amber-200 text-amber-800 rounded-xl p-4 flex items-start gap-3"
    >
      <Info className="w-5 h-5 mt-0.5 shrink-0" aria-hidden="true" />
      <div className="flex-1 text-sm">
        <p className="font-medium">
          Your portfolio is undergoing reconciliation with our back-office
          records as of {runAt}. The figures below may be revised. Your
          relationship manager has been notified.
        </p>
        {notes && (
          <p
            className="mt-1 text-xs text-amber-700"
            title={notes}
            aria-label={`Reconciliation notes: ${notes}`}
          >
            Details: {notes}
          </p>
        )}
        <a
          href="/dashboard/methodology#reconciliation"
          className="inline-block mt-2 text-xs font-medium text-amber-900 underline hover:text-amber-950"
        >
          Learn more
        </a>
      </div>
    </div>
  );
}
