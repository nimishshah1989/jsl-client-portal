'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { apiFetch } from '@/lib/api';
import Sidebar from '@/components/layout/Sidebar';
import Spinner from '@/components/ui/Spinner';

/**
 * Dashboard layout with sidebar + main content.
 * Auth-protected: redirects to /login if not authenticated.
 */
export default function DashboardLayout({ children }) {
  const router = useRouter();
  const [authChecked, setAuthChecked] = useState(false);

  const [user, setUser] = useState(null);

  useEffect(() => {
    async function checkAuth() {
      try {
        const data = await apiFetch('/auth/me');
        setUser(data);
        setAuthChecked(true);
      } catch {
        router.replace('/login');
      }
    }
    checkAuth();
  }, [router]);

  if (!authChecked) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <Spinner size="lg" />
      </div>
    );
  }

  return (
    <div className="flex min-h-screen bg-slate-50">
      <Sidebar user={user} />
      <main className="flex-1 lg:ml-0 pt-14 lg:pt-0">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6">
          {children}
        </div>
      </main>
    </div>
  );
}
