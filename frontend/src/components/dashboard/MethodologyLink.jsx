'use client';

import Link from 'next/link';
import { Calculator, ArrowRight } from 'lucide-react';

/**
 * Link to the Calculation Methodology page.
 * Displayed at the bottom of the dashboard.
 */
export default function MethodologyLink() {
  return (
    <div className="bg-white rounded-xl border border-slate-200 p-5">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="p-2.5 bg-teal-50 rounded-xl">
            <Calculator className="w-5 h-5 text-teal-600" />
          </div>
          <div>
            <h3 className="text-sm font-semibold text-slate-800">
              Calculation Methodology
            </h3>
            <p className="text-xs text-slate-500 mt-0.5">
              How every number on your dashboard is computed — formulae, inputs, and worked examples
            </p>
          </div>
        </div>
        <Link
          href="/dashboard/methodology"
          className="inline-flex items-center gap-1.5 px-4 py-2 bg-teal-600 text-white text-sm font-medium rounded-lg hover:bg-teal-700 transition-colors"
        >
          View
          <ArrowRight className="w-4 h-4" />
        </Link>
      </div>
    </div>
  );
}
