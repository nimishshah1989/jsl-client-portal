'use client';

import LoginForm from '@/components/auth/LoginForm';

export default function LoginPage() {
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
