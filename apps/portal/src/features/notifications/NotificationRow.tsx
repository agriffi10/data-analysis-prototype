import {Link} from 'react-router';
import {formatRelativeTime} from '../../lib/format';
import {cx} from '../../lib/cx';
import {useIsMobile} from '../../lib/useBreakpoint';
import {useFeature} from '../feature-flags';
import {isSafeInAppPath} from './notificationLink';
import type {Notification} from './notifications.types';

type NotificationRowProps = {
  notification: Notification;
  onMarkRead: (id: string) => void;
};

/**
 * One notification row, rendered as a self-contained card.
 *
 * Unread rows get an accent wash, marker dot, and a Mark-read control; the unread
 * state is also conveyed in a visually-hidden label so it's never color-only.
 * There is no delete — notifications are only ever marked read.
 */
export function NotificationRow({notification, onMarkRead}: NotificationRowProps) {
  const {id, message, read, timestamp, link} = notification;
  // The MESSAGE is the link — never a trailing "here". That gives the anchor an
  // accessible name that says where it goes, and keeps the row a single target.
  // A link that could leave this origin is dropped entirely (open-redirect guard),
  // leaving exactly the plain-text row a producer supplying no link would produce.
  // SPEC-163: a link into a disabled feature is dropped, leaving the plain-text row a producer
  // supplying no link would have produced. The route gate already refuses the destination, so
  // this is not a disclosure — it is the difference between an inbox that offers a dead end and
  // one that does not. Notifications themselves are never gated: the record of what happened
  // outlives the surface that would show it.
  const dataQualityEnabled = useFeature('dataQuality');
  const gated = link?.startsWith('/data-quality') && !dataQualityEnabled;
  const to = !gated && isSafeInAppPath(link) ? link : undefined;
  // Mark-read is a compact trailing control at ≥ tablet; below the message as a
  // full-width touch target on mobile (SPEC-102 FR-003). Mount-gated so exactly
  // one button exists (a CSS swap would duplicate it in the DOM).
  const isMobile = useIsMobile();

  return (
    <li
      className={cx(
        'flex items-start gap-3 rounded-md border p-4',
        read ? 'border-border bg-surface' : 'border-accent-border bg-accent-soft'
      )}>
      {/* Unread marker — decorative. Read rows keep a same-width empty slot so the
          message column stays aligned with unread rows. */}
      {read ? (
        <span
          aria-hidden="true"
          className="w-2 flex-none"
        />
      ) : (
        <span
          aria-hidden="true"
          className="mt-1.5 h-2 w-2 flex-none rounded-full bg-accent"
        />
      )}

      <div className="min-w-0 flex-1">
        <p className={cx('break-words text-sm leading-relaxed', read ? 'text-text-2' : 'font-semibold text-text')}>
          {!read && <span className="sr-only">Unread: </span>}
          {to ? (
            <Link
              to={to}
              className="underline underline-offset-2 hover:text-accent-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent">
              {message}
            </Link>
          ) : (
            message
          )}
        </p>
        <p className="mt-1 text-xs text-text-3">{formatRelativeTime(timestamp)}</p>

        {/* Mobile: full-width 34px button below the message + timestamp. */}
        {!read && isMobile && (
          <button
            type="button"
            onClick={() => onMarkRead(id)}
            className="mt-2 h-[34px] w-full rounded-md border border-border text-xs font-medium text-text-2 hover:bg-surface-2 hover:text-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent">
            Mark read
          </button>
        )}
      </div>

      {/* ≥ tablet: compact trailing control. */}
      {!read && !isMobile && (
        <button
          type="button"
          onClick={() => onMarkRead(id)}
          className="flex-none rounded-md px-2 py-1 text-xs font-medium text-text-2 hover:bg-surface-2 hover:text-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent">
          Mark read
        </button>
      )}
    </li>
  );
}
