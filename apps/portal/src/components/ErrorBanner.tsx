import {Banner, type BannerVariant} from './Banner';
import {toUserMessage} from '../lib/errorMessages';

type Props = {
  /** A thrown value or a ServiceResult error object; mapped via `toUserMessage`. */
  error: unknown;
  /** Defaults to 'danger'; pass 'warning' for a partial-failure summary, etc. */
  variant?: BannerVariant;
  onDismiss?: () => void;
  role?: 'alert' | 'status';
  className?: string;
};

/**
 * A {@link Banner} that renders user-safe error text mapped through
 * {@link toUserMessage} — never the raw `.message`. Use for
 * danger/error banners so wording stays consistent with toasts and inline surfaces.
 *
 * @example
 * <ErrorBanner error={result.error} onDismiss={clearError} />
 */
export function ErrorBanner({error, variant = 'danger', onDismiss, role, className}: Props) {
  const {title, message} = toUserMessage(error);
  return (
    <Banner
      variant={variant}
      title={title}
      onDismiss={onDismiss}
      role={role}
      className={className}>
      {message}
    </Banner>
  );
}
