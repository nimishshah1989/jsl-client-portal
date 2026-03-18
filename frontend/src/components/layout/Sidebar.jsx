'use client';

import { useState } from 'react';
import { usePathname } from 'next/navigation';
import Link from 'next/link';
import { useAuth } from '@/hooks/useAuth';
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

export default function Sidebar() {
  const { user, logout } = useAuth();
  const pathname = usePathname();
  const [mobileOpen, setMobileOpen] = useState(false);
  const [activeSection, setActiveSection] = useState('summary');

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

        {/* Logout */}
        <div className="p-4 border-t border-slate-100">
          <button
            onClick={logout}
            className="w-full flex items-center gap-3 px-3 py-2 text-sm font-medium text-slate-500 hover:text-red-600 hover:bg-red-50 rounded-lg transition-colors"
          >
            <LogOut className="w-4 h-4" />
            Sign Out
          </button>
        </div>
      </aside>
    </>
  );
}
