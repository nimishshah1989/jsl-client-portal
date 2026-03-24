'use client';

import ClientHeader from '@/components/dashboard/ClientHeader';
import SummaryCards from '@/components/dashboard/SummaryCards';
import NavChart from '@/components/dashboard/NavChart';
import PerformanceTable from '@/components/dashboard/PerformanceTable';
import GrowthViz from '@/components/dashboard/GrowthViz';
import AllocationBar from '@/components/dashboard/AllocationBar';
import HoldingsTable from '@/components/dashboard/HoldingsTable';
import UnderwaterChart from '@/components/dashboard/UnderwaterChart';
import RiskScorecard from '@/components/dashboard/RiskScorecard';
import MonthlyReturns from '@/components/dashboard/MonthlyReturns';
import TransactionHistory from '@/components/dashboard/TransactionHistory';
import MethodologyLink from '@/components/dashboard/MethodologyLink';

/**
 * Main dashboard page — single scrollable page with all sections.
 * Each section has an id for anchor navigation from the sidebar.
 */
export default function DashboardPage() {
  return (
    <div className="space-y-4 sm:space-y-6 min-w-0 max-w-full overflow-hidden">
      {/* 1. Client Header */}
      <section id="header">
        <ClientHeader />
      </section>

      {/* 2. Summary Cards */}
      <section id="summary">
        <SummaryCards />
      </section>

      {/* 3. NAV Performance Chart */}
      <section id="performance">
        <NavChart />
      </section>

      {/* 4. Performance Summary Table */}
      <section id="performance-table">
        <PerformanceTable />
      </section>

      {/* 5. Growth Visualization */}
      <section id="growth">
        <GrowthViz />
      </section>

      {/* 6. Allocation Labels + Holdings Table */}
      <section id="allocation">
        <AllocationBar />
      </section>
      <section id="holdings">
        <HoldingsTable />
      </section>

      {/* 7. Underwater Chart */}
      <section id="drawdown">
        <UnderwaterChart />
      </section>

      {/* 8. Risk Scorecard */}
      <section id="risk">
        <RiskScorecard />
      </section>

      {/* 9. Monthly Returns */}
      <section id="monthly">
        <MonthlyReturns />
      </section>

      {/* 10. Transaction History */}
      <section id="transactions">
        <TransactionHistory />
      </section>

      {/* 11. Methodology Link */}
      <section id="methodology-link">
        <MethodologyLink />
      </section>
    </div>
  );
}
