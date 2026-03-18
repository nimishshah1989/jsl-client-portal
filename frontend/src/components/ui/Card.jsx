/**
 * Reusable card component matching JIP design system.
 */
export default function Card({ children, className = '', ...props }) {
  return (
    <div
      className={`bg-white rounded-xl border border-slate-200 p-5 ${className}`}
      {...props}
    >
      {children}
    </div>
  );
}

export function CardTitle({ children, className = '' }) {
  return (
    <h3 className={`text-sm font-semibold text-slate-800 mb-3 ${className}`}>
      {children}
    </h3>
  );
}
