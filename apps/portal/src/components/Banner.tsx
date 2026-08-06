import {cx} from '../lib/cx';

export type BannerVariant = 'success' | 'warning' | 'danger' | 'info';

type BannerProps = {
  variant: BannerVariant;
  /** Bold first line above the body. */
  title?: string;
  children?: React.ReactNode;
  /**
   * Renders a "Try again" action inside the banner. For the retry-a-failed-read case
   * both list pages had hand-rolled as an underlined button in the body — same markup,
   * same wording, twice.
   */
  retry?: () => void;
  /** Override the retry action's wording. */
  retryLabel?: string;
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
export function Banner({
  variant,
  title,
  children,
  retry,
  retryLabel = 'Try again',
  onDismiss,
  role = 'alert',
  className
}: BannerProps) {
  return (
    <div
      role={role}
      className={cx('rounded-lg border p-3 text-sm flex items-start gap-3', VARIANTS[variant], className)}>
      <div className="min-w-0 flex-1">
        {title && <p className="font-medium">{title}</p>}
        {children}
        {retry && (
          <button
            type="button"
            onClick={retry}
            className="font-semibold underline underline-offset-2 hover:opacity-80 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent">
            {retryLabel}
          </button>
        )}
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
