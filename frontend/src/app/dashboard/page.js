'use client';

import ClientHeader from '@/components/dashboard/ClientHeader';
import SummaryCards from '@/components/dashboard/SummaryCards';
import NavChart from '@/components/dashboard/NavChart';
import PerformanceTable from '@/components/dashboard/PerformanceTable';
import GrowthViz from '@/components/dashboard/GrowthViz';
import AllocationCharts from '@/components/dashboard/AllocationCharts';
import HoldingsTable from '@/components/dashboard/HoldingsTable';
import UnderwaterChart from '@/components/dashboard/UnderwaterChart';
import RiskScorecard from '@/components/dashboard/RiskScorecard';
import MonthlyReturns from '@/components/dashboard/MonthlyReturns';
import TransactionHistory from '@/components/dashboard/TransactionHistory';
import Commentary from '@/components/dashboard/Commentary';
import MethodologyLink from '@/components/dashboard/MethodologyLink';

/**
 * Main dashboard page — single scrollable page with all 12 sections.
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

      {/* 6. Allocation Charts */}
      <section id="allocation">
        <AllocationCharts />
      </section>

      {/* 7. Holdings Table */}
      <section id="holdings">
        <HoldingsTable />
      </section>

      {/* 8. Underwater Chart */}
      <section id="drawdown">
        <UnderwaterChart />
      </section>

      {/* 9. Risk Scorecard */}
      <section id="risk">
        <RiskScorecard />
      </section>

      {/* 10. Monthly Returns */}
      <section id="monthly">
        <MonthlyReturns />
      </section>

      {/* 11. Transaction History */}
      <section id="transactions">
        <TransactionHistory />
      </section>

      {/* 12. Commentary */}
      <section id="commentary">
        <Commentary />
      </section>

      {/* 13. Methodology Link */}
      <section id="methodology-link">
        <MethodologyLink />
      </section>
    </div>
  );
}
