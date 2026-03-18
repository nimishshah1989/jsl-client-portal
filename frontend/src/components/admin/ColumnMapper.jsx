'use client';

import { useState } from 'react';
import Button from '@/components/ui/Button';

/**
 * Column mapper preview: shows first 10 rows and auto-mapped columns.
 * Allows user to confirm or adjust column mapping before proceeding.
 */
export default function ColumnMapper({ preview, onConfirm, onCancel }) {
  if (!preview) return null;

  const { columns = [], rows = [], auto_mapping = {} } = preview;
  const [mapping, setMapping] = useState(auto_mapping);

  function handleMappingChange(sourceCol, targetCol) {
    setMapping((prev) => ({ ...prev, [sourceCol]: targetCol }));
  }

  return (
    <div className="bg-white rounded-xl border border-slate-200 p-5">
      <h3 className="text-base font-semibold text-slate-800 mb-3">
        Column Mapping Preview
      </h3>
      <p className="text-sm text-slate-500 mb-4">
        Showing first {rows.length} rows. Verify the column mapping below.
      </p>

      {/* Preview table */}
      <div className="overflow-x-auto mb-4 max-h-64 border border-slate-200 rounded-lg">
        <table className="w-full text-xs">
          <thead className="sticky top-0">
            <tr className="bg-slate-50">
              {columns.map((col) => (
                <th key={col} className="px-3 py-2 text-left text-slate-500 font-medium whitespace-nowrap">
                  {col}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {rows.map((row, idx) => (
              <tr key={idx} className="hover:bg-slate-50">
                {columns.map((col) => (
                  <td key={col} className="px-3 py-1.5 text-slate-600 whitespace-nowrap font-mono">
                    {row[col] ?? ''}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Mapping controls */}
      <div className="grid grid-cols-2 md:grid-cols-3 gap-3 mb-4">
        {columns.map((col) => (
          <div key={col} className="text-sm">
            <label className="text-xs text-slate-500 mb-1 block">{col}</label>
            <select
              value={mapping[col] || ''}
              onChange={(e) => handleMappingChange(col, e.target.value)}
              className="w-full border border-slate-300 rounded-lg px-2 py-1.5 text-sm text-slate-800 focus:ring-2 focus:ring-teal-500 focus:border-teal-500"
            >
              <option value="">-- Skip --</option>
              <option value="date">Date</option>
              <option value="nav_value">NAV</option>
              <option value="corpus">Corpus</option>
              <option value="cash_pct">Cash %</option>
              <option value="ucc">Client Code</option>
              <option value="symbol">Symbol</option>
              <option value="quantity">Quantity</option>
              <option value="price">Price</option>
              <option value="amount">Amount</option>
              <option value="txn_type">Txn Type</option>
            </select>
          </div>
        ))}
      </div>

      <div className="flex gap-3">
        <Button variant="primary" size="sm" onClick={() => onConfirm(mapping)}>
          Confirm & Upload
        </Button>
        <Button variant="secondary" size="sm" onClick={onCancel}>
          Cancel
        </Button>
      </div>
    </div>
  );
}
