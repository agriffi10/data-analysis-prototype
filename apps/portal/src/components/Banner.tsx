import { cx } from '../lib/cx';

export type BannerVariant = 'success' | 'warning' | 'danger' | 'info';

type BannerProps = {
  variant: BannerVariant;
  title?: string; // bold first line (optional)
  children: React.ReactNode; // body content
  onDismiss?: () => void; // if provided, renders a Dismiss button
  role?: 'alert' | 'status'; // defaults to 'alert'
  className?: string;
};

const VARIANTS: Record<BannerVariant, string> = {
  success: 'bg-success-soft border-success-soft text-success',
  warning: 'bg-warning-soft border-warning-soft text-warning',
  danger: 'bg-danger-soft border-danger-soft text-danger',
  info: 'bg-accent-soft border-accent-soft text-accent-text',
};

// Dismissible status banner (SPEC-028) — inline success / warning / danger /
// info feedback. Used for delete/move results and download/write errors.
export function Banner({
  variant,
  title,
  children,
  onDismiss,
  role = 'alert',
  className,
}: BannerProps) {
  return (
    <div
      role={role}
      className={cx(
        'rounded-lg border p-3 text-sm flex items-start gap-3',
        VARIANTS[variant],
        className,
      )}
    >
      <div className="min-w-0 flex-1">
        {title && <p className="font-medium">{title}</p>}
        {children}
      </div>
      {onDismiss && (
        <button
          type="button"
          onClick={onDismiss}
          className="ml-auto flex-shrink-0 text-xs font-medium opacity-70 hover:underline hover:opacity-100"
        >
          Dismiss
        </button>
      )}
    </div>
  );
}
