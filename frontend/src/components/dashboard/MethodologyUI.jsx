'use client';

import { useState } from 'react';
import { ChevronDown, ChevronRight } from 'lucide-react';
import { formatPct } from '@/lib/format';

/**
 * Accordion item for a single metric.
 */
export function AccordionItem({ title, value, children }) {
  const [open, setOpen] = useState(false);

  return (
    <div className="border border-slate-200 rounded-xl overflow-hidden">
      <button
        onClick={() => setOpen(!open)}
        className="w-full flex items-center justify-between px-5 py-4 bg-white hover:bg-slate-50 transition-colors text-left"
      >
        <div className="flex items-center gap-3">
          {open ? (
            <ChevronDown className="w-4 h-4 text-teal-600 shrink-0" />
          ) : (
            <ChevronRight className="w-4 h-4 text-slate-400 shrink-0" />
          )}
          <span className="font-semibold text-slate-800">{title}</span>
        </div>
        {value != null && (
          <span className="font-mono tabular-nums text-teal-600 font-medium text-sm">
            {typeof value === 'string' ? value : formatPct(value)}
          </span>
        )}
      </button>
      {open && (
        <div className="px-5 pb-5 pt-2 border-t border-slate-100 bg-white">
          <div className="space-y-4 text-sm text-slate-600">
            {children}
          </div>
        </div>
      )}
    </div>
  );
}

/**
 * Section header for grouping metrics.
 */
export function SectionHeader({ title }) {
  return (
    <h3 className="text-base font-semibold text-slate-800 mt-6 mb-3 first:mt-0">{title}</h3>
  );
}

/**
 * Formula display block.
 */
export function Formula({ children }) {
  return (
    <div className="bg-slate-50 rounded-lg p-4 font-mono text-sm text-slate-700">
      {children}
    </div>
  );
}

/**
 * Worked example block with client's actual numbers.
 */
export function WorkedExample({ children }) {
  return (
    <div className="bg-slate-50 rounded-lg p-4">
      <p className="font-medium text-slate-700 mb-2">Your numbers:</p>
      {children}
    </div>
  );
}

/**
 * Interpretation note.
 */
export function Interpretation({ children }) {
  return (
    <div className="text-xs text-slate-500">
      {children}
    </div>
  );
}
