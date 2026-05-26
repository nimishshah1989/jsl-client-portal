'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import LoginForm from '@/components/auth/LoginForm';
import Spinner from '@/components/ui/Spinner';
import { apiFetch } from '@/lib/api';

export default function LoginPage() {
  const router = useRouter();
  const [checking, setChecking] = useState(true);

  useEffect(() => {
    let cancelled = false;
    async function redirectIfLoggedIn() {
      try {
        const me = await apiFetch('/auth/me');
        if (cancelled) return;
        if (me?.is_admin) {
          router.replace('/admin');
        } else {
          router.replace('/dashboard');
        }
      } catch {
        // 401 (or other) — user really is logged out, show the form.
        if (!cancelled) setChecking(false);
      }
    }
    redirectIfLoggedIn();
    return () => {
      cancelled = true;
    };
  }, [router]);

  if (checking) {
    return (
      <div className="min-h-screen bg-slate-50 flex items-center justify-center">
        <Spinner size="lg" />
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-slate-50 flex flex-col items-center justify-center p-4">
      <LoginForm />
      <p className="mt-6 text-xs text-slate-400 text-center max-w-md">
        Jhaveri Securities Limited | SEBI PMS Reg. No: INP000006888
        <br />
        Investments are subject to market risks. Read all related documents carefully.
      </p>
    </div>
  );
}
