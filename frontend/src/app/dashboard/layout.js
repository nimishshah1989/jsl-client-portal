'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { apiFetch } from '@/lib/api';
import Sidebar from '@/components/layout/Sidebar';
import Spinner from '@/components/ui/Spinner';
import { ArrowLeft } from 'lucide-react';

/**
 * Dashboard layout with sidebar + main content.
 * Auth-protected: redirects to /login if not authenticated.
 * Shows "Back to Admin" banner when viewing as impersonated client.
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
        setUser(data);
        // If the user is NOT an admin but came from admin (check sessionStorage flag)
        // OR if the referrer was /admin
        const wasAdmin = sessionStorage.getItem('admin_viewing');
        if (wasAdmin) {
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
    // Re-login as admin by calling /auth/login won't work without password.
    // Instead, we store admin credentials aren't available, so just redirect
    // to login page which will bounce admin to /admin.
    sessionStorage.removeItem('admin_viewing');
    window.location.href = '/login';
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
              Back to Admin (re-login required)
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
