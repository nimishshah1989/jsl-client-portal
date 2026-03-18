'use client';

import { MessageSquareText } from 'lucide-react';

/**
 * Monthly fund manager commentary section.
 * Displays static or DB-fetched commentary.
 */
export default function Commentary() {
  return (
    <div className="bg-white rounded-xl border border-slate-200 p-5">
      <div className="flex items-center gap-2 mb-4">
        <MessageSquareText className="w-5 h-5 text-teal-600" />
        <h2 className="text-xl font-semibold text-slate-800">
          Fund Manager Commentary
        </h2>
      </div>

      <div className="bg-slate-50 rounded-lg p-4 text-sm text-slate-600 leading-relaxed">
        <p className="mb-3">
          Markets continued their recovery trajectory during the month, supported by strong
          earnings momentum in select sectors. We maintained a balanced approach with tactical
          cash allocation to navigate near-term volatility.
        </p>
        <p className="mb-3">
          Key portfolio actions during the month included selective profit booking in
          momentum-driven names that reached stretched valuations, while initiating fresh
          positions in quality businesses available at reasonable valuations.
        </p>
        <p>
          We continue to focus on our core investment philosophy of owning high-quality
          businesses with strong competitive moats, run by capable management teams, available
          at reasonable valuations. The portfolio remains well-diversified across sectors with
          a bias towards domestic consumption and financial services.
        </p>
      </div>

      <p className="text-xs text-slate-400 mt-3">
        Commentary is updated monthly by the fund management team.
      </p>
    </div>
  );
}
