import {Link} from 'react-router';
import {formatRelativeTime} from '../../lib/format';
import {cx} from '../../lib/cx';
import {useIsMobile} from '../../lib/useBreakpoint';
import {useFeature} from '../feature-flags';
import {isSafeInAppPath, reviewHref} from './notificationLink';
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
  // a link into a disabled feature is dropped, leaving the plain-text row a producer
  // supplying no link would have produced. The route gate already refuses the destination, so
  // this is not a disclosure — it is the difference between an inbox that offers a dead end and
  // one that does not. Notifications themselves are never gated: the record of what happened
  // outlives the surface that would show it.
  //
  // A map rather than one hard-coded prefix, because a second producer
  // arrived and the single-prefix form silently did nothing for it. A file-send notification
  // deep-links into `/files`, and with `files` off that route swaps its element — so the link was
  // a live anchor into the unavailable page. The space-owner variant is worse than a dead end:
  // with `sharedWorkspaces` off the route does not READ `?space=`, resolves the personal space,
  // and then discards a prefix that does not start with it — landing the owner in their own
  // files with no banner, while the message says where to look. That is the "link that silently
  // lands someone at their space root" this rule exists to prevent.
  const flags = {
    files: useFeature('files'),
    dataQuality: useFeature('dataQuality'),
    sharedWorkspaces: useFeature('sharedWorkspaces')
  };
  const gated =
    (link?.startsWith('/data-quality') && !flags.dataQuality) ||
    (link?.startsWith('/files') && !flags.files) ||
    // Only the SPACE variant needs the workspaces flag: a personal-space link is a `/files` link
    // like any other, and gating it on a flag it does not depend on would drop a working link.
    (link?.includes('?space=') && !flags.sharedWorkspaces);
  const to = !gated && isSafeInAppPath(link) ? link : undefined;
  // A notification whose producer named the items it could not do gets a second, SEPARATE
  // control into the view that can act on them. It is a SIBLING of the message anchor and never
  // nested inside it: the message is deliberately the whole link, so an interactive control
  // within it is `nested-interactive` — an axe failure this repo has shipped twice.
  //
  // The href is the row's own destination with the request id attached, built with
  // URLSearchParams rather than by picking a separator: appending to a link that may already
  // carry `?space=` is exactly where a hand-rolled `?` produces a URL nobody validated. The
  // value is encoded on the way in, and the reader has already refused anything that could
  // change a URL — two gates, because this one arrives from outside the SPA.
  //
  // Falling back to the file browser's root is deliberate. Reachability of the conflicts must
  // not depend on a PREFIX link, which is a strictly more failure-prone thing than the request
  // id the view actually needs — a user who closed the submitting tab has nowhere else to go.
  const {payload} = notification;
  const hasConflicts = (payload?.conflicts?.length ?? 0) > 0;
  const review = payload && hasConflicts && !gated && flags.files ? reviewHref(to, payload.requestId) : undefined;
  // Mark-read is a compact trailing control at ≥ tablet; below the message as a
  // full-width touch target on mobile. Mount-gated so exactly
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

        {review && (
          <p className="mt-2">
            <Link
              to={review}
              className="text-xs font-medium underline underline-offset-2 hover:text-accent-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent">
              Review conflicts
            </Link>
          </p>
        )}

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
