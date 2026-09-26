import {Link} from 'react-router';
import {formatRelativeTime} from '../../lib/format';
import {cx} from '../../lib/cx';
import {useIsMobile} from '../../lib/useBreakpoint';
import {useCanFollowLink} from '../feature-flags';
import {useQueryClient} from '@tanstack/react-query';
import {invalidateListing} from '../file-browser';
import {filesLinkListing, isSafeInAppPath, reviewHref} from './notificationLink';
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
  // A link that could leave this origin is dropped entirely (open-redirect guard), and so is a
  // link into a feature this user cannot see, leaving exactly the plain-text row a producer
  // supplying no link would have produced. The route gate already refuses the destination, so
  // this is not a disclosure — it is the difference between an inbox that offers a dead end and
  // one that does not. Notifications themselves are never gated: the record of what happened
  // outlives the surface that would show it.
  //
  // The gate is DERIVED from the destination, so a new producer or route is covered without a
  // clause here. The space variant is worse than a dead end: with `sharedWorkspaces` off `/files`
  // does not READ `?space=`, resolves the personal space and discards a prefix that does not start
  // with it, landing the owner in their own files with no banner while the message says where to look.
  const canFollow = useCanFollowLink();
  const gated = !!link && !canFollow(link);
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
  const reviewTarget = payload && hasConflicts && !gated ? reviewHref(to, payload.requestId) : undefined;
  const review = reviewTarget && canFollow(reviewTarget) ? reviewTarget : undefined;
  // Mark-read is a compact trailing control at ≥ tablet; below the message as a
  // full-width touch target on mobile. Mount-gated so exactly
  // one button exists (a CSS swap would duplicate it in the DOM).
  const isMobile = useIsMobile();

  // FOLLOWING a `/files` link refreshes the folder it lands on, so a file a control plane has
  // just written is present on arrival rather than a refetch later.
  //
  // A MECHANISM over the link, not a clause for one producer: results conversion, file send and
  // archive all deep-link into a folder they have just written to, and a per-producer version
  // would silently do nothing for the next one — which is the failure the derived gate above
  // exists to fix. BOTH anchors carry it, for the same reason: `reviewHref` is this same path
  // with a request id attached, so it lands on the same listing and a user who arrived that way
  // would be the one person the refresh missed.
  //
  // The notification's ARRIVAL still invalidates nothing. Notification-driven listing
  // reconciliation is the mechanism the file-ops provider records as deliberately not used: the
  // poll is a minute wide and pauses on a hidden tab, so it would be a refresh that arrives late
  // for the user who is looking at the folder and never for the one who is not — and that user
  // is already covered by the listing's own refetch on focus.
  const queryClient = useQueryClient();
  const listing = to ? filesLinkListing(to) : undefined;
  const refreshDestination = listing
    ? () => void invalidateListing(queryClient, listing.bucket, listing.prefix)
    : undefined;

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
              onClick={refreshDestination}
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
              onClick={refreshDestination}
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
