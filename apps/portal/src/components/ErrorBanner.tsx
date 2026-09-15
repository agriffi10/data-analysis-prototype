import {Banner, type BannerVariant} from './Banner';
import {ErrorDetails} from './ErrorDetails';
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
 * {@link toUserMessage} — never the raw `.message`. When the mapper judged a failed
 * query's own message safe to show, it sits beneath the sentence in a closed Details
 * disclosure. Use for danger/error banners so wording stays consistent with toasts
 * and inline surfaces.
 *
 * @example
 * <ErrorBanner error={result.error} onDismiss={clearError} />
 */
export function ErrorBanner({error, variant = 'danger', onDismiss, role, className}: Props) {
  const {title, message, detail} = toUserMessage(error);
  return (
    <Banner
      variant={variant}
      title={title}
      onDismiss={onDismiss}
      role={role}
      className={className}>
      {message}
      <ErrorDetails detail={detail} />
    </Banner>
  );
}
