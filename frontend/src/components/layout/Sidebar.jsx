'use client';

import { useState, useCallback } from 'react';
import { usePathname, useRouter } from 'next/navigation';
import Link from 'next/link';
import { apiFetch } from '@/lib/api';
import {
  BarChart3,
  TrendingUp,
  Wallet,
  TrendingDown,
  Shield,
  CalendarDays,
  ClipboardList,
  Calculator,
  LogOut,
  Menu,
  X,
  ChevronLeft,
  KeyRound,
} from 'lucide-react';

const NAV_ITEMS = [
  { id: 'summary', label: 'Overview', icon: BarChart3, href: '#summary' },
  { id: 'performance', label: 'Performance', icon: TrendingUp, href: '#performance' },
  { id: 'holdings', label: 'Holdings', icon: Wallet, href: '#holdings' },
  { id: 'drawdown', label: 'Drawdown', icon: TrendingDown, href: '#drawdown' },
  { id: 'risk', label: 'Risk', icon: Shield, href: '#risk' },
  { id: 'monthly', label: 'Monthly', icon: CalendarDays, href: '#monthly' },
  { id: 'transactions', label: 'Transactions', icon: ClipboardList, href: '#transactions' },
  { id: 'methodology', label: 'Methodology', icon: Calculator, href: '/dashboard/methodology', isPage: true },
];

function ChangePasswordModal({ onClose }) {
  const [oldPw, setOldPw] = useState('');
  const [newPw, setNewPw] = useState('');
  const [confirmPw, setConfirmPw] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState(null);
  const [success, setSuccess] = useState(false);

  async function handleSubmit(e) {
    e.preventDefault();
    setError(null);
    if (newPw.length < 8) {
      setError('New password must be at least 8 characters.');
      return;
    }
    if (newPw !== confirmPw) {
      setError('New passwords do not match.');
      return;
    }
    setSubmitting(true);
    try {
      await apiFetch('/auth/change-password', {
        method: 'POST',
        body: JSON.stringify({ old_password: oldPw, new_password: newPw }),
      });
      setSuccess(true);
    } catch (err) {
      setError(err.message || 'Password change failed.');
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/40" onClick={onClose}>
      <div
        className="bg-white rounded-xl border border-slate-200 shadow-xl w-full max-w-sm mx-4 p-6"
        onClick={(e) => e.stopPropagation()}
      >
        <h3 className="text-lg font-semibold text-slate-800 mb-4">Change Password</h3>
        {success ? (
          <div>
            <p className="text-emerald-600 text-sm mb-4">Password changed successfully.</p>
            <button onClick={onClose} className="w-full py-2 rounded-lg bg-teal-600 text-white text-sm font-medium hover:bg-teal-700">
              Close
            </button>
          </div>
        ) : (
          <form onSubmit={handleSubmit} className="space-y-3">
            {error && <p className="text-red-600 text-xs">{error}</p>}
            <div>
              <label className="block text-xs text-slate-500 mb-1">Current Password</label>
              <input
                type="password"
                value={oldPw}
                onChange={(e) => setOldPw(e.target.value)}
                required
                className="w-full px-3 py-2 rounded-lg border border-slate-200 text-sm focus:outline-none focus:ring-2 focus:ring-teal-500"
              />
            </div>
            <div>
              <label className="block text-xs text-slate-500 mb-1">New Password</label>
              <input
                type="password"
                value={newPw}
                onChange={(e) => setNewPw(e.target.value)}
                required
                minLength={8}
                className="w-full px-3 py-2 rounded-lg border border-slate-200 text-sm focus:outline-none focus:ring-2 focus:ring-teal-500"
              />
            </div>
            <div>
              <label className="block text-xs text-slate-500 mb-1">Confirm New Password</label>
              <input
                type="password"
                value={confirmPw}
                onChange={(e) => setConfirmPw(e.target.value)}
                required
                minLength={8}
                className="w-full px-3 py-2 rounded-lg border border-slate-200 text-sm focus:outline-none focus:ring-2 focus:ring-teal-500"
              />
            </div>
            <button
              type="submit"
              disabled={submitting}
              className="w-full py-2 rounded-lg bg-teal-600 text-white text-sm font-medium hover:bg-teal-700 disabled:opacity-50"
            >
              {submitting ? 'Changing...' : 'Change Password'}
            </button>
          </form>
        )}
      </div>
    </div>
  );
}

export default function Sidebar({ user }) {
  const router = useRouter();
  const pathname = usePathname();
  const [mobileOpen, setMobileOpen] = useState(false);
  const [activeSection, setActiveSection] = useState('summary');
  const [showPasswordModal, setShowPasswordModal] = useState(false);

  const logout = useCallback(async () => {
    try {
      await apiFetch('/auth/logout', { method: 'POST' });
    } catch {
      // Logout even if API fails
    } finally {
      router.push('/login');
    }
  }, [router]);

  function handleNavClick(item) {
    if (!item.isPage) {
      setActiveSection(item.id);
      const el = document.getElementById(item.id);
      if (el) {
        el.scrollIntoView({ behavior: 'smooth', block: 'start' });
      }
    }
    setMobileOpen(false);
  }

  const isMethodologyPage = pathname === '/dashboard/methodology';

  return (
    <>
      {/* Mobile header bar */}
      <div className="lg:hidden fixed top-0 left-0 right-0 z-50 bg-white border-b border-slate-200 px-4 py-3 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <button
            onClick={() => setMobileOpen(!mobileOpen)}
            className="p-1.5 rounded-lg hover:bg-slate-100"
          >
            {mobileOpen ? <X className="w-5 h-5" /> : <Menu className="w-5 h-5" />}
          </button>
          <span className="text-sm font-semibold text-teal-600">JSL Portal</span>
        </div>
        {user && (
          <span className="text-xs text-slate-500 truncate max-w-[160px]">
            {user.name || user.client_name}
          </span>
        )}
      </div>

      {/* Mobile overlay */}
      {mobileOpen && (
        <div
          className="lg:hidden fixed inset-0 z-40 bg-black/30"
          onClick={() => setMobileOpen(false)}
        />
      )}

      {/* Sidebar */}
      <aside
        className={`
          fixed top-0 left-0 z-40 h-full w-64 bg-white border-r border-slate-200
          flex flex-col transition-transform duration-200
          lg:translate-x-0 lg:static lg:z-auto
          ${mobileOpen ? 'translate-x-0' : '-translate-x-full'}
        `}
      >
        {/* Logo area */}
        <div className="p-5 border-b border-slate-100">
          <h2 className="text-lg font-bold text-teal-600">JSL Client Portal</h2>
          {user && (
            <div className="mt-2">
              <p className="text-sm font-medium text-slate-800 truncate">
                {user.name || user.client_name}
              </p>
              <p className="text-xs text-slate-400 truncate">
                {user.portfolio_name || 'PMS Equity'}
              </p>
            </div>
          )}
        </div>

        {/* Back to dashboard link on methodology page */}
        {isMethodologyPage && (
          <Link
            href="/dashboard"
            className="flex items-center gap-2 px-5 py-3 text-sm text-teal-600 hover:bg-teal-50 border-b border-slate-100"
          >
            <ChevronLeft className="w-4 h-4" />
            Back to Dashboard
          </Link>
        )}

        {/* Navigation */}
        <nav className="flex-1 py-3 overflow-y-auto">
          {NAV_ITEMS.map((item) => {
            const isActive = item.isPage
              ? pathname === item.href
              : !isMethodologyPage && activeSection === item.id;

            if (item.isPage) {
              return (
                <Link
                  key={item.id}
                  href={item.href}
                  onClick={() => setMobileOpen(false)}
                  className={`
                    flex items-center gap-3 px-5 py-2.5 text-sm font-medium transition-colors
                    ${isActive
                      ? 'text-teal-600 bg-teal-50 border-r-2 border-teal-600'
                      : 'text-slate-600 hover:text-slate-800 hover:bg-slate-50'
                    }
                  `}
                >
                  <item.icon className="w-4 h-4" />
                  {item.label}
                </Link>
              );
            }

            return (
              <button
                key={item.id}
                onClick={() => handleNavClick(item)}
                className={`
                  w-full flex items-center gap-3 px-5 py-2.5 text-sm font-medium transition-colors text-left
                  ${isActive
                    ? 'text-teal-600 bg-teal-50 border-r-2 border-teal-600'
                    : 'text-slate-600 hover:text-slate-800 hover:bg-slate-50'
                  }
                `}
              >
                <item.icon className="w-4 h-4" />
                {item.label}
              </button>
            );
          })}
        </nav>

        {/* Change Password + Logout */}
        <div className="p-4 border-t border-slate-100 space-y-1">
          <button
            onClick={() => setShowPasswordModal(true)}
            className="w-full flex items-center gap-3 px-3 py-2 text-sm font-medium text-slate-500 hover:text-teal-600 hover:bg-teal-50 rounded-lg transition-colors"
          >
            <KeyRound className="w-4 h-4" />
            Change Password
          </button>
          <button
            onClick={logout}
            className="w-full flex items-center gap-3 px-3 py-2 text-sm font-medium text-slate-500 hover:text-red-600 hover:bg-red-50 rounded-lg transition-colors"
          >
            <LogOut className="w-4 h-4" />
            Sign Out
          </button>
        </div>
      </aside>

      {showPasswordModal && (
        <ChangePasswordModal onClose={() => setShowPasswordModal(false)} />
      )}
    </>
  );
}
