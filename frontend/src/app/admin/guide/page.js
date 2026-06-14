'use client';

export const dynamic = 'force-dynamic';

import Link from 'next/link';
import { BookOpen, Calculator, ArrowRight } from 'lucide-react';
import {
  AccordionItem,
  SectionHeader,
  Formula,
  Interpretation,
} from '@/components/dashboard/MethodologyUI';

/**
 * Admin Guide — an in-portal reference for how the portal classifies, ages,
 * aggregates, and unifies client data, plus the firm-level calculations.
 * Static content (no data fetch); reuses the methodology accordion UI.
 */
export default function AdminGuidePage() {
  return (
    <div className="max-w-3xl mx-auto">
      {/* Header */}
      <div className="flex items-center gap-3 mb-2">
        <div className="p-2.5 bg-teal-50 rounded-xl">
          <BookOpen className="w-6 h-6 text-teal-600" />
        </div>
        <div>
          <h1 className="text-2xl font-bold text-slate-800">Admin Guide</h1>
          <p className="text-sm text-slate-500">
            How the portal classifies, ages, aggregates and unifies client data — and how the firm numbers are computed.
          </p>
        </div>
      </div>
      <p className="text-xs text-slate-400 mb-6">
        Reflects the unified-login go-live (Jun 2026). Benchmark: NIFTY 50 (all strategies, interim) ·
        Risk-free rate: 6.50% · Trading days/yr: 252.
      </p>

      {/* 1. Strategy classification */}
      <SectionHeader title="1. Strategy classification" />
      <p className="text-sm text-slate-600 mb-3">
        Every portfolio (one per PMS code/UCC) is tagged with a strategy derived from its{' '}
        <span className="font-medium">code suffix</span>. This single rule
        (<code className="text-xs bg-slate-100 px-1 py-0.5 rounded">backend/services/classification.py</code>)
        is shared by the one-time backfill and ongoing ingestion, so a code always maps to the same bucket.
      </p>
      <div className="space-y-2 mb-2">
        <AccordionItem title="The four buckets">
          <ul className="space-y-2">
            <li><span className="font-semibold text-slate-700">LEADERS</span> — the default. Any code that does not match a suffix below (e.g. <code className="text-xs bg-slate-100 px-1 rounded">BJ53</code>, <code className="text-xs bg-slate-100 px-1 rounded">AC04MF</code>).</li>
            <li><span className="font-semibold text-slate-700">PASSIVE</span> — code ends in <code className="text-xs bg-slate-100 px-1 rounded">PASS</code> (e.g. <code className="text-xs bg-slate-100 px-1 rounded">BJ53PASS</code>).</li>
            <li><span className="font-semibold text-slate-700">IND11</span> — code ends in <code className="text-xs bg-slate-100 px-1 rounded">IND</code> (e.g. <code className="text-xs bg-slate-100 px-1 rounded">BJ53IND</code>).</li>
            <li><span className="font-semibold text-slate-700">CLOSED</span> — code ends in <code className="text-xs bg-slate-100 px-1 rounded">CLOSE</code> or <code className="text-xs bg-slate-100 px-1 rounded">CLO</code> → archived (see §2).</li>
          </ul>
          <Interpretation>
            The <span className="font-medium">Combined / Leaders / Passive / IND11</span> selector on the dashboard filters every aggregate to that bucket. CLOSED is always excluded from live views.
          </Interpretation>
        </AccordionItem>
      </div>

      {/* 2. Account lifecycle */}
      <SectionHeader title="2. Account lifecycle — Active, Dormant, Closed" />
      <p className="text-sm text-slate-600 mb-3">
        The daily PMS NAV file only reports <span className="font-medium">active</span> accounts. When an
        account is redeemed it simply stops appearing — so "stale" NAV is the signal that money has left.
      </p>
      <div className="space-y-2">
        <AccordionItem title="Active vs Inactive (the 30-day window)">
          <p>
            A portfolio is <span className="font-medium">active</span> if its latest NAV is within{' '}
            <span className="font-mono">30 days</span> of the firm's most recent NAV date. Stale ones are
            hidden from live views by default.
          </p>
          <Formula>active if  latest_nav_date ≥ (firm_latest_nav_date − 30 days)</Formula>
          <Interpretation>
            The admin <span className="font-medium">"Include inactive portfolios"</span> checkbox flips this
            off and adds dormant sleeves back at their last-known value (Total AUM rises). Default: active-only.
            Source: <code className="text-xs bg-slate-100 px-1 rounded">services/strategy_filter.py</code>.
          </Interpretation>
        </AccordionItem>
        <AccordionItem title="Dormant → Closed (the 90-day flag)">
          <p>
            Accounts with no NAV for <span className="font-mono">&gt; 90 days</span> (or no NAV at all — empty
            stubs) are flagged <code className="text-xs bg-slate-100 px-1 rounded">is_closed = true</code> by{' '}
            <code className="text-xs bg-slate-100 px-1 rounded">scripts/flag_dormant_portfolios.py</code>.
            Closing is <span className="font-medium">reversible</span> and <span className="font-medium">retains all data</span> — it
            just removes the account from live AUM and the Combined view so the firm total reflects real, current money.
          </p>
          <Interpretation>
            Jun 2026 run: 80 portfolios flagged → live AUM dropped from ₹90.23 Cr to ₹83.43 Cr (the genuine figure).
            If a flagged account turns out to still be invested, un-close it (a one-line reversal).
          </Interpretation>
        </AccordionItem>
      </div>

      {/* 3. Combined view */}
      <SectionHeader title="3. The Combined view" />
      <p className="text-sm text-slate-600 mb-3">
        One person can hold several portfolios ("sleeves") across strategies. The Combined view rolls a
        person's <span className="font-medium">live</span> sleeves into one picture.
      </p>
      <div className="space-y-2">
        <AccordionItem title="What adds, and what is recomputed">
          <p>
            Only <span className="font-medium">₹ quantities are additive</span> — AUM, invested, holding
            value/quantity sum across sleeves. <span className="font-medium">Returns and ratios are never
            summed</span>; CAGR, Sharpe, Beta, XIRR, Max Drawdown are recomputed from the combined
            time-weighted series.
          </p>
          <Formula>
            <div>Combined AUM = Σ (live sleeves&apos; latest NAV)</div>
            <div>Combined CAGR = recomputed from combined TWR (NOT Σ of per-sleeve CAGRs)</div>
          </Formula>
          <Interpretation>Closed sleeves are excluded. Every combined endpoint is reconciled in tests: combined == sum of the person's live portfolios.</Interpretation>
        </AccordionItem>
        <AccordionItem title="Carry-forward across mismatched date ranges">
          <p>
            If one sleeve stopped reporting earlier than another, the combined total still counts its{' '}
            <span className="font-medium">last known value</span> (forward-filled to the union of dates)
            rather than dropping it — so a person with a paused sleeve isn't under-counted. Genuinely
            redeemed sleeves are excluded via <code className="text-xs bg-slate-100 px-1 rounded">is_closed</code> instead.
          </p>
        </AccordionItem>
      </div>

      {/* 4. Unified login */}
      <SectionHeader title="4. Unified login (one login per person)" />
      <p className="text-sm text-slate-600 mb-3">
        Historically each PMS code was its own login. The unified-login merge collapses a person's codes
        into a single account so they log in once and land on their Combined view.
      </p>
      <div className="space-y-2">
        <AccordionItem title="How people are grouped & which login survives">
          <ul className="space-y-2">
            <li>Codes are grouped by <span className="font-medium">exact full name</span> (interim; a manual override map handles spelling drift / same-name collisions).</li>
            <li>The <span className="font-medium">survivor</span> is the code the person already uses (active first, then most-recent login, then lowest id).</li>
            <li>Non-survivor codes are soft-retired by pointing <code className="text-xs bg-slate-100 px-1 rounded">cpp_clients.merged_into</code> at the survivor; their portfolios + all data re-parent onto the survivor.</li>
            <li><span className="font-medium">Old usernames still work</span> — a retired login aliases onto the survivor (and lands on the Combined view). Nobody is stranded.</li>
          </ul>
          <Interpretation>
            Jun 2026 merge: 44 codes retired across 36 people; 0 retired logins had ever been used (zero
            disruption). Example: Bhadresh's 6 codes (BJ53, BJ53MF, BJ53NEW, BJ53AML, BJ53PASS, BJ53IND) →
            one login (<span className="font-mono">BJ53</span>) owning 6 portfolios.
          </Interpretation>
        </AccordionItem>
        <AccordionItem title="Fully-redeemed people show ₹0 Combined">
          <p>
            If <span className="font-medium">every</span> sleeve a person holds is closed/redeemed, their
            Combined view correctly reads ₹0 (their history is retained and still viewable per portfolio).
            This is expected — not an error.
          </p>
        </AccordionItem>
      </div>

      {/* 5. Admin dashboard calculations */}
      <SectionHeader title="5. Admin dashboard — how the firm numbers are computed" />
      <p className="text-sm text-slate-600 mb-3">
        All firm aggregates are computed <span className="font-medium">per portfolio</span> (not per client),
        so a person holding several sleeves is counted in full.
      </p>
      <div className="space-y-2">
        <AccordionItem title="Total AUM, Invested, Cash">
          <Formula>
            <div>Total AUM = Σ over every in-scope portfolio of its OWN latest NAV</div>
            <div>Total Invested = Σ each portfolio&apos;s latest invested (corpus)</div>
            <div>Cash = Σ (ETF + ledger cash + bank); fallback = NAV × Liquidity%</div>
          </Formula>
          <Interpretation>
            Per-portfolio-latest (not "latest per client") is what keeps the total correct after the merge —
            a unified client's sleeves all count. Closed/inactive excluded unless "Include inactive" is on.
            Source: <code className="text-xs bg-slate-100 px-1 rounded">services/admin_analytics.py</code>.
          </Interpretation>
        </AccordionItem>
        <AccordionItem title="Blended CAGR / Sharpe / Max Drawdown">
          <Formula>Blended metric = Σ (portfolio metric × portfolio AUM) / Σ AUM</Formula>
          <p>AUM-weighted across portfolios — larger sleeves move the blended figure more. Ratios are weighted, never summed.</p>
        </AccordionItem>
        <AccordionItem title="Strategy Summary table & 30-day flows">
          <p>
            Rows = Total AUM / CAGR / Deposits (30d) / Withdrawals (30d) / Max Drawdown; columns =
            Combined / Leaders / Passive / IND11.
          </p>
          <Formula>
            <div>Deposits (30d) = Σ INFLOW on cpp_cash_flows in the last 30 days</div>
            <div>Withdrawals (30d) = Σ OUTFLOW on cpp_cash_flows in the last 30 days</div>
          </Formula>
          <Interpretation>Deposits and withdrawals are separate rolling sums (not netted), so both gross figures are visible.</Interpretation>
        </AccordionItem>
        <AccordionItem title="Top performers (one row per person)">
          <p>
            The Top-5 lists (by CAGR / NAV / invested) show <span className="font-medium">one row per
            person</span>: a unified client's sleeves are rolled up (AUM &amp; invested summed, ratios
            AUM-weighted) so the same name never appears multiple times.
          </p>
        </AccordionItem>
      </div>

      {/* 6. Data pipeline */}
      <SectionHeader title="6. Data pipeline (what an upload does)" />
      <div className="space-y-2">
        <AccordionItem title="Upload → ingest → compute">
          <ol className="space-y-1 list-decimal list-inside">
            <li>Upload the two PMS files (NAV report + transaction report).</li>
            <li>Stateful row-by-row parse → upsert into <code className="text-xs bg-slate-100 px-1 rounded">cpp_nav_series</code> / <code className="text-xs bg-slate-100 px-1 rounded">cpp_transactions</code> (per code).</li>
            <li>Fetch NIFTY 50 benchmark (yfinance), date-align, store on each NAV row.</li>
            <li>Detect corpus changes → derive XIRR cash flows.</li>
            <li>Run the risk engine → <code className="text-xs bg-slate-100 px-1 rounded">cpp_risk_metrics</code> + <code className="text-xs bg-slate-100 px-1 rounded">cpp_drawdown_series</code>.</li>
            <li>Recompute holdings from transactions (weighted-average cost).</li>
          </ol>
          <Interpretation>
            Risk metrics are <span className="font-medium">pre-computed and stored</span> after each upload;
            the dashboard reads stored values, so data is current as of the last upload. Use{' '}
            <span className="font-medium">Recompute Risk</span> on the dashboard to force a refresh.
          </Interpretation>
        </AccordionItem>
      </div>

      {/* 7. Risk metric formulae */}
      <SectionHeader title="7. Risk metric formulae" />
      <p className="text-sm text-slate-600 mb-3">
        Every per-client risk metric (CAGR, XIRR, Volatility, Sharpe, Sortino, Max Drawdown, Alpha, Beta,
        Up/Down Capture, Information Ratio, Tracking Error, Ulcer Index, monthly profile) is defined with
        its plain-English meaning, exact formula and a worked example on the client-facing methodology page.
      </p>
      <Link
        href="/dashboard/methodology"
        className="inline-flex items-center gap-2 px-4 py-2 text-sm font-medium text-teal-600 bg-teal-50 hover:bg-teal-100 rounded-lg transition-colors"
      >
        <Calculator className="w-4 h-4" />
        Open the full calculation methodology
        <ArrowRight className="w-4 h-4" />
      </Link>

      <div className="h-10" />
    </div>
  );
}
