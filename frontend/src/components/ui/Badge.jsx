import { TXN_TYPE_STYLES } from '@/lib/constants';

/**
 * Color badge for status and transaction types.
 * Follows JIP design system color conventions.
 */

const STATUS_STYLES = {
  active: { bg: 'bg-emerald-100', text: 'text-emerald-700' },
  inactive: { bg: 'bg-slate-100', text: 'text-slate-500' },
  pending: { bg: 'bg-amber-100', text: 'text-amber-700' },
  error: { bg: 'bg-red-100', text: 'text-red-700' },
  success: { bg: 'bg-emerald-100', text: 'text-emerald-700' },
};

export default function Badge({ children, variant = 'default', className = '' }) {
  const styles = STATUS_STYLES[variant] || TXN_TYPE_STYLES[variant] || {
    bg: 'bg-slate-100',
    text: 'text-slate-600',
  };

  return (
    <span
      className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${styles.bg} ${styles.text} ${className}`}
    >
      {children}
    </span>
  );
}

/**
 * Transaction type badge with automatic color mapping.
 */
export function TxnBadge({ type }) {
  const styles = TXN_TYPE_STYLES[type] || { bg: 'bg-slate-100', text: 'text-slate-600' };
  return (
    <span
      className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${styles.bg} ${styles.text}`}
    >
      {type}
    </span>
  );
}
