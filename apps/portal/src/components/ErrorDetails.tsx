import {cx} from '../lib/cx';

type ErrorDetailsProps = {
  /** The engine's own words, from `toUserMessage(...).detail`; nothing renders without them. */
  detail?: string;
  className?: string;
};

/**
 * A closed "Details" disclosure beneath an error's sentence, holding Athena's own message for a
 * query that failed on the user's own SQL — the line, the column and the reason the friendly
 * sentence leaves out. Closed by default, so the sentence stays what a user reads first.
 *
 * @example
 * const {message, detail} = toUserMessage(error);
 * <p>{message}</p>
 * <ErrorDetails detail={detail} />
 */
export function ErrorDetails({detail, className}: ErrorDetailsProps) {
  if (!detail) return null;
  return (
    <details className={cx('mt-1 text-sm', className)}>
      <summary className="min-h-[24px] cursor-pointer rounded-sm font-medium hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent">
        Details
      </summary>
      <pre className="mt-1 whitespace-pre-wrap break-words font-mono text-xs">{detail}</pre>
    </details>
  );
}
