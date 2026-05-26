'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { apiFetch } from '@/lib/api';
import Spinner from '@/components/ui/Spinner';

/**
 * Tech Docs layout — admin-only access gate.
 *
 * The technical documentation page exposes internal system architecture,
 * security model, deployment topology, and reconciliation/role notes that
 * should not be readable by end clients. Gate it behind admin auth using
 * the same pattern as /admin/* (see frontend/src/app/admin/layout.js).
 *
 * Behavior:
 *   - Unauthenticated  → redirect to /login
 *   - Authenticated non-admin → redirect to /dashboard
 *   - Authenticated admin → render children
 *
 * Tracks audit item C15 in PRODUCTION_READINESS.md.
 */
export default function TechDocsLayout({ children }) {
  const router = useRouter();
  const [authChecked, setAuthChecked] = useState(false);

  useEffect(() => {
    async function checkAdmin() {
      try {
        const user = await apiFetch('/auth/me');
        if (!user?.is_admin) {
          router.replace('/dashboard');
          return;
        }
        setAuthChecked(true);
      } catch {
        router.replace('/login');
      }
    }
    checkAdmin();
  }, [router]);

  if (!authChecked) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <Spinner size="lg" />
      </div>
    );
  }

  return <>{children}</>;
}
