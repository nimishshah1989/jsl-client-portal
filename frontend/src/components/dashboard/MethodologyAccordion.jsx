'use client';

import { useState } from 'react';

/**
 * Expandable accordion section for the methodology page.
 * Uses CSS max-height transition for smooth expand/collapse.
 */
export function AccordionGroup({ title, children }) {
  const [open, setOpen] = useState(false);

  return (
    <div className="border border-slate-200 rounded-xl overflow-hidden">
      <button
        onClick={() => setOpen(!open)}
        className="w-full flex items-center justify-between px-5 py-4 bg-slate-50 hover:bg-slate-100 transition-colors text-left"
      >
        <span className="text-sm font-semibold text-slate-800">{title}</span>
        <svg
          className={`w-5 h-5 text-slate-400 transition-transform duration-200 ${open ? 'rotate-180' : ''}`}
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
          strokeWidth={1.5}
        >
          <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 8.25l-7.5 7.5-7.5-7.5" />
        </svg>
      </button>
      <div
        className={`transition-all duration-300 ease-in-out overflow-hidden ${
          open ? 'max-h-[5000px] opacity-100' : 'max-h-0 opacity-0'
        }`}
      >
        <div className="divide-y divide-slate-100">{children}</div>
      </div>
    </div>
  );
}

/**
 * Single methodology accordion item.
 * Props:
 *   name       — metric name
 *   value      — current value (formatted string)
 *   explanation — plain-English description
 *   formula     — math formula string
 *   inputs      — object of input labels/values for worked example
 *   calculation — step-by-step worked example string
 *   interpretation — scale/interpretation guide
 *   benchmarkValue — benchmark comparison value
 */
export function AccordionItem({
  name,
  value,
  explanation,
  formula,
  inputs,
  calculation,
  interpretation,
  benchmarkValue,
}) {
  const [open, setOpen] = useState(false);

  return (
    <div>
      <button
        onClick={() => setOpen(!open)}
        className="w-full flex items-center justify-between px-5 py-3.5 hover:bg-slate-50 transition-colors text-left"
      >
        <span className="text-sm font-medium text-slate-700">{name}</span>
        <div className="flex items-center gap-3">
          <span className="font-mono text-sm text-teal-600 tabular-nums">{value ?? '--'}</span>
          <svg
            className={`w-4 h-4 text-slate-400 transition-transform duration-200 ${open ? 'rotate-180' : ''}`}
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
            strokeWidth={1.5}
          >
            <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 8.25l-7.5 7.5-7.5-7.5" />
          </svg>
        </div>
      </button>
      <div
        className={`transition-all duration-300 ease-in-out overflow-hidden ${
          open ? 'max-h-[2000px] opacity-100' : 'max-h-0 opacity-0'
        }`}
      >
        <div className="px-5 pb-4 space-y-4 text-sm text-slate-600">
          {/* Explanation */}
          {explanation && <p>{explanation}</p>}

          {/* Formula */}
          {formula && (
            <div className="bg-slate-50 rounded-lg p-4 font-mono text-sm text-slate-700">
              {formula}
            </div>
          )}

          {/* Worked Example */}
          {inputs && (
            <div className="bg-slate-50 rounded-lg p-4">
              <p className="font-medium text-slate-700 mb-2">Your numbers:</p>
              {Object.entries(inputs).map(([label, val]) => (
                <p key={label} className="text-slate-600">
                  {label} = <span className="font-mono">{val}</span>
                </p>
              ))}
              {calculation && (
                <p className="mt-2 font-semibold text-slate-800">
                  = <span className="text-teal-600 font-mono">{calculation}</span>
                </p>
              )}
            </div>
          )}

          {/* Interpretation */}
          {interpretation && (
            <p className="text-xs text-slate-500">{interpretation}</p>
          )}

          {/* Benchmark comparison */}
          {benchmarkValue != null && (
            <p className="text-xs text-slate-500">
              Benchmark (NIFTY 50): <span className="font-mono">{benchmarkValue}</span>
            </p>
          )}
        </div>
      </div>
    </div>
  );
}
