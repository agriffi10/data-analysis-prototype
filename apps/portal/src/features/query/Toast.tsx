import { useEffect } from 'react';
import { cx } from '../../lib/cx';

export type ToastState = {
  variant: 'success' | 'danger' | 'info';
  message: string;
};

type Props = ToastState & {
  onDismiss: () => void;
  // SPEC-049: optional inline action (e.g. "View in Files"). Auto-dismiss is
  // suppressed while an action is offered so it stays reachable.
  action?: { label: string; onClick: () => void };
};

const AUTO_DISMISS_MS = 4000;

// SPEC-044 FR-006: minimal transient toast for Drop-table (and DDL-fetch)
// feedback — the app's first toast primitive. Fixed bottom-right, accessible
// live region, manually dismissible. Success/error auto-dismiss; `info` (used as
// a "working…" notice) stays until the caller clears it. Never blocks interaction.
export function Toast({ variant, message, onDismiss, action }: Props) {
  useEffect(() => {
    if (variant === 'info') return; // caller clears the working notice
    if (action) return; // keep an actionable toast until the user acts/dismisses
    const t = setTimeout(onDismiss, AUTO_DISMISS_MS);
    return () => clearTimeout(t);
  }, [variant, message, onDismiss, action]);

  return (
    <div
      role={variant === 'danger' ? 'alert' : 'status'}
      aria-live={variant === 'danger' ? 'assertive' : 'polite'}
      className={cx(
        'fixed bottom-5 right-5 z-50 flex max-w-sm items-start gap-3 rounded-lg border px-4 py-3 text-sm shadow-lg',
        variant === 'success' && 'border-success bg-success-soft text-success',
        variant === 'danger' && 'border-danger bg-danger-soft text-danger',
        variant === 'info' && 'border-border bg-surface text-text-2'
      )}
    >
      <span className="min-w-0 flex-1">{message}</span>
      {action && (
        <button
          type="button"
          onClick={action.onClick}
          className="flex-none rounded-sm font-semibold underline underline-offset-2 hover:opacity-80 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
        >
          {action.label}
        </button>
      )}
      <button
        type="button"
        aria-label="Dismiss"
        onClick={onDismiss}
        className="grid h-6 w-6 flex-none place-items-center rounded-sm opacity-70 hover:opacity-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
      >
        <svg
          viewBox="0 0 16 16"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          className="h-3.5 w-3.5"
          aria-hidden="true"
        >
          <path strokeLinecap="round" d="M2 2l12 12M14 2L2 14" />
        </svg>
      </button>
    </div>
  );
}
