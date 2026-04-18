'use client';

import { ShieldCheck } from 'lucide-react';

export default function RegulatoryDisclaimer() {
  return (
    <div className="bg-slate-50 border border-slate-200 rounded-xl p-4 text-xs text-slate-500 space-y-2">
      <div className="flex items-center gap-2 text-slate-600 font-medium text-sm">
        <ShieldCheck className="h-4 w-4 text-teal-600" />
        <span>Important Disclosures</span>
      </div>
      <div className="space-y-1.5 leading-relaxed">
        <p>
          Past performance is not indicative of future results. Investments in securities
          are subject to market risks. Read all related documents carefully before investing.
        </p>
        <p>
          Portfolio values shown are based on daily NAV computed from PMS backoffice data.
          Actual realised values may differ due to transaction costs, taxes, and settlement timing.
        </p>
        <p>
          Risk metrics (Sharpe, Sortino, Beta, etc.) are computed using historical data and
          may not predict future risk. Benchmark comparison uses NIFTY 50 TRI unless stated otherwise.
        </p>
        <p>
          Jhaveri Securities Limited is a SEBI-registered Portfolio Manager.
          CIN: U65990MH1994PLC076920 | SEBI PMS Reg. No: INP000006888
        </p>
        <p className="text-slate-400">
          This portal is for information purposes only and does not constitute investment advice.
          For grievances, write to compliance@jslwealth.in or call +91-22-4037-6700.
        </p>
      </div>
    </div>
  );
}
