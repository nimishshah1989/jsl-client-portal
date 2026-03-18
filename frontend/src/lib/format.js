/**
 * Indian number formatting utilities for JSL Client Portfolio Portal.
 * All financial values use Indian grouping (lakh/crore) — never Western.
 */

/**
 * Format a number with Indian grouping: 1,23,45,678
 * @param {number} value
 * @param {number} decimals
 * @returns {string}
 */
export function formatIndianNumber(value, decimals = 2) {
  if (value == null || value === '') return '--';
  value = Number(value);
  if (isNaN(value)) return '--';
  const isNegative = value < 0;
  const absVal = Math.abs(value);
  const parts = absVal.toFixed(decimals).split('.');
  let intPart = parts[0];
  const decPart = parts[1];

  // Indian grouping: last 3, then groups of 2
  if (intPart.length > 3) {
    const last3 = intPart.slice(-3);
    let rest = intPart.slice(0, -3);
    const groups = [];
    while (rest.length > 2) {
      groups.unshift(rest.slice(-2));
      rest = rest.slice(0, -2);
    }
    if (rest.length > 0) groups.unshift(rest);
    intPart = groups.join(',') + ',' + last3;
  }

  const formatted = decPart ? `${intPart}.${decPart}` : intPart;
  return isNegative ? `-${formatted}` : formatted;
}

/**
 * Format as INR with rupee symbol: ₹1,23,456.00
 * @param {number} value
 * @param {number} decimals
 * @returns {string}
 */
export function formatINR(value, decimals = 2) {
  if (value == null || value === '') return '--';
  value = Number(value);
  if (isNaN(value)) return '--';
  return `\u20B9${formatIndianNumber(value, decimals)}`;
}

/**
 * Format as short INR: ₹48.50L or ₹67.45 Cr
 * @param {number} value
 * @returns {string}
 */
export function formatINRShort(value) {
  if (value == null || value === '') return '--';
  value = Number(value);
  if (isNaN(value)) return '--';
  const isNegative = value < 0;
  const absVal = Math.abs(value);
  const prefix = isNegative ? '-' : '';

  if (absVal >= 1e7) {
    return `${prefix}\u20B9${(absVal / 1e7).toFixed(2)} Cr`;
  }
  if (absVal >= 1e5) {
    return `${prefix}\u20B9${(absVal / 1e5).toFixed(2)}L`;
  }
  if (absVal >= 1e3) {
    return `${prefix}\u20B9${formatIndianNumber(absVal, 0)}`;
  }
  return `${prefix}\u20B9${absVal.toFixed(2)}`;
}

/**
 * Format percentage with +/- prefix: +35.64% or -5.05%
 * @param {number} value — already in %, e.g. 35.64
 * @param {number} decimals
 * @returns {string}
 */
export function formatPct(value, decimals = 2) {
  if (value == null || value === '') return '--';
  const num = Number(value);
  if (isNaN(num)) return '--';
  const prefix = num > 0 ? '+' : '';
  return `${prefix}${num.toFixed(decimals)}%`;
}

/**
 * Format a date string to "DD MMM YYYY" e.g. "13 Mar 2026"
 * @param {string|Date} dateVal
 * @returns {string}
 */
export function formatDate(dateVal) {
  if (!dateVal) return '--';
  const d = new Date(dateVal);
  if (isNaN(d.getTime())) return '--';
  const months = [
    'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
    'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec',
  ];
  return `${d.getDate()} ${months[d.getMonth()]} ${d.getFullYear()}`;
}

/**
 * Format date as "MMM YY" for chart axis: "Mar 26"
 * @param {string|Date} dateVal
 * @returns {string}
 */
export function formatDateShort(dateVal) {
  if (!dateVal) return '';
  const d = new Date(dateVal);
  if (isNaN(d.getTime())) return '';
  const months = [
    'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
    'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec',
  ];
  return `${months[d.getMonth()]} ${String(d.getFullYear()).slice(2)}`;
}

/**
 * Return color class for a value: green if positive, red if negative
 * @param {number} value
 * @returns {string}
 */
export function pnlColor(value) {
  if (value == null || value === '') return 'text-slate-800';
  value = Number(value);
  if (isNaN(value)) return 'text-slate-800';
  if (value > 0) return 'text-emerald-600';
  if (value < 0) return 'text-red-600';
  return 'text-slate-800';
}
