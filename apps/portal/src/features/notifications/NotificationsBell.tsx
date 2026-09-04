import {NavLink} from 'react-router';
import {
  HEADER_CONTROL,
  HEADER_CONTROL_ACTIVE,
  HEADER_CONTROL_IDLE,
  HEADER_CONTROL_LABEL
} from '../../components/headerControl';
import {BellIcon} from '../../components/icons';
import {cx} from '../../lib/cx';

type NotificationsBellProps = {
  hasUnread: boolean;
  unreadCount: number;
};

/**
 * Header notifications control — a bell, the word `Notifications`, and a link to
 * `/notifications` (not a drawer toggle).
 *
 * Shows a numeric unread badge (capped at "9+") so additional arrivals stay visible;
 * the count is also carried in the accessible name so the indicator is never color-only.
 *
 * The badge hangs off the ICON, not off the control. Once there is a label the control's
 * top-right corner is past the end of a word, which is nowhere near the bell it is counting.
 */
export function NotificationsBell({hasUnread, unreadCount}: NotificationsBellProps) {
  const label = hasUnread ? `Notifications, ${unreadCount} unread` : 'Notifications, none unread';
  const badge = unreadCount > 9 ? '9+' : String(unreadCount);

  return (
    <NavLink
      to="/notifications"
      aria-label={label}
      className={({isActive}) => cx(HEADER_CONTROL, isActive ? HEADER_CONTROL_ACTIVE : HEADER_CONTROL_IDLE)}>
      {/* `tablet:mr-1.5` is the badge's clearance, and it is measured rather than eyeballed: the
          badge overhangs the icon by 5.25px (`-right-1.5` against a 14px root) and the row's own
          gap is the same 5.25, so without this the badge's right edge lands exactly on the `N` of
          the label. Only at `tablet` and up, because below that there is no label to clear and the
          margin would be dead width on the bar with the least of it. */}
      <span className="relative flex-none tablet:mr-1.5">
        <BellIcon className="h-5 w-5" />
        {hasUnread && (
          // Numeric count badge (accent pill). Decorative — the count lives in the
          // link's aria-label — so it's aria-hidden to avoid double-announcing.
          <span
            aria-hidden="true"
            className={cx(
              'absolute -right-1.5 -top-1 inline-flex h-4 min-w-4 items-center justify-center rounded-full px-1',
              'bg-accent text-[10px] font-semibold leading-none text-white ring-2 ring-surface'
            )}>
            {badge}
          </span>
        )}
      </span>
      <span className={HEADER_CONTROL_LABEL}>Notifications</span>
    </NavLink>
  );
}
