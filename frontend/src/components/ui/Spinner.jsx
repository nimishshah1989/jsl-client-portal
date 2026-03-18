'use client';

/**
 * Loading spinner with configurable size.
 * Uses teal-600 to match JIP design system.
 */
export default function Spinner({ size = 'md', className = '' }) {
  const sizeMap = {
    sm: 'h-4 w-4 border-2',
    md: 'h-8 w-8 border-2',
    lg: 'h-12 w-12 border-3',
  };

  return (
    <div
      className={`animate-spin rounded-full border-teal-600 border-t-transparent ${sizeMap[size] || sizeMap.md} ${className}`}
      role="status"
      aria-label="Loading"
    />
  );
}
