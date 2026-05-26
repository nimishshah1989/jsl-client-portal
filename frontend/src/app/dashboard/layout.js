'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { apiFetch, apiPost } from '@/lib/api';
import Sidebar from '@/components/layout/Sidebar';
import Spinner from '@/components/ui/Spinner';
import { ArrowLeft } from 'lucide-react';

/**
 * Dashboard layout with sidebar + main content.
 * Auth-protected: redirects to /login if not authenticated.
 * Shows "Back to Admin" banner when viewing as an impersonated client.
 *
 * If the caller is an admin without an active impersonation session
 * (no `admin_viewing` sessionStorage flag), bounce them to /admin —
 * otherwise admin queries on the dashboard route would 401 with
 * "No active portfolio" since the admin user has no portfolio.
 */
export default function DashboardLayout({ children }) {
  const router = useRouter();
  const [authChecked, setAuthChecked] = useState(false);
  const [user, setUser] = useState(null);
  const [isImpersonated, setIsImpersonated] = useState(false);

  useEffect(() => {
    async function checkAuth() {
      try {
        const data = await apiFetch('/auth/me');
        const adminViewing = sessionStorage.getItem('admin_viewing');

        // Admin landed on /dashboard without impersonating — send them home.
        if (data?.is_admin && !adminViewing) {
          router.replace('/admin');
          return;
        }

        setUser(data);
        if (adminViewing) {
          setIsImpersonated(true);
        }
        setAuthChecked(true);
      } catch {
        router.replace('/login');
      }
    }
    checkAuth();
  }, [router]);

  async function handleBackToAdmin() {
    try {
      await apiPost('/admin/stop-impersonate', {});
    } catch {
      // Even if the call fails, fall through to clearing the flag —
      // the admin's access_token cookie is independent of the
      // impersonation_token, so they remain authenticated as admin.
    }
    sessionStorage.removeItem('admin_viewing');
    router.replace('/admin');
  }

  if (!authChecked) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <Spinner size="lg" />
      </div>
    );
  }

  return (
    <div className="flex min-h-screen bg-slate-50 overflow-x-hidden">
      <Sidebar user={user} />
      <main className="flex-1 min-w-0 lg:ml-0 pt-14 lg:pt-0 overflow-x-hidden">
        {isImpersonated && (
          <div className="bg-amber-50 border-b border-amber-200 px-4 py-2 flex items-center justify-between">
            <span className="text-sm text-amber-800">
              Viewing as: <strong>{user?.name}</strong>
            </span>
            <button
              onClick={handleBackToAdmin}
              className="flex items-center gap-1 text-sm font-medium text-amber-700 hover:text-amber-900"
            >
              <ArrowLeft className="w-4 h-4" />
              Back to Admin
            </button>
          </div>
        )}
        <div className="max-w-7xl mx-auto px-3 sm:px-6 lg:px-8 py-4 sm:py-6">
          {children}
        </div>
      </main>
    </div>
  );
}
