import {cx} from '../lib/cx';

export type BannerVariant = 'success' | 'warning' | 'danger' | 'info';

type BannerProps = {
  variant: BannerVariant;
  /** Bold first line above the body. */
  title?: string;
  children: React.ReactNode;
  /** When provided, renders a Dismiss button that calls it. */
  onDismiss?: () => void;
  /** ARIA live-region role; defaults to 'alert'. */
  role?: 'alert' | 'status';
  className?: string;
};

const VARIANTS: Record<BannerVariant, string> = {
  success: 'bg-success-soft border-success-soft text-success',
  warning: 'bg-warning-soft border-warning-soft text-warning',
  danger: 'bg-danger-soft border-danger-soft text-danger',
  info: 'bg-accent-soft border-accent-soft text-accent-text'
};

/**
 * Inline status banner for success / warning / danger / info feedback
 * (e.g. delete/move results, download errors). Announced via a live region
 * (`role="alert"` by default; pass `role="status"` for non-urgent messages).
 *
 * @example
 * <Banner variant="danger" title="Delete failed" onDismiss={() => setError(null)}>
 *   Some items could not be removed.
 * </Banner>
 */
export function Banner({variant, title, children, onDismiss, role = 'alert', className}: BannerProps) {
  return (
    <div
      role={role}
      className={cx('rounded-lg border p-3 text-sm flex items-start gap-3', VARIANTS[variant], className)}>
      <div className="min-w-0 flex-1">
        {title && <p className="font-medium">{title}</p>}
        {children}
      </div>
      {onDismiss && (
        <button
          type="button"
          onClick={onDismiss}
          className="ml-auto shrink-0 text-xs font-medium opacity-70 hover:underline hover:opacity-100">
          Dismiss
        </button>
      )}
    </div>
  );
}
