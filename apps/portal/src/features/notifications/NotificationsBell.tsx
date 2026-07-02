import {NavLink} from 'react-router-dom';
import {BellIcon} from '../../components/icons';
import {cx} from '../../lib/cx';

type NotificationsBellProps = {
  hasUnread: boolean;
  unreadCount: number;
};

/**
 * Header notifications control — a link to `/notifications` (not a drawer toggle).
 *
 * Shows a numeric unread badge (capped at "9+") so additional arrivals stay visible;
 * the count is also carried in the accessible name so the indicator is never color-only.
 */
export function NotificationsBell({hasUnread, unreadCount}: NotificationsBellProps) {
  const label = hasUnread ? `Notifications, ${unreadCount} unread` : 'Notifications, none unread';
  const badge = unreadCount > 9 ? '9+' : String(unreadCount);

  return (
    <NavLink
      to="/notifications"
      aria-label={label}
      className={({isActive}) =>
        cx(
          'relative inline-flex h-8 w-8 items-center justify-center rounded-md transition-colors',
          'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent',
          isActive ? 'bg-surface-2 text-accent-text' : 'text-text-3 hover:bg-surface-2 hover:text-text'
        )
      }>
      <BellIcon className="h-5 w-5" />
      {hasUnread && (
        // Numeric count badge (accent pill). Decorative — the count lives in the
        // link's aria-label — so it's aria-hidden to avoid double-announcing.
        <span
          aria-hidden="true"
          className={cx(
            'absolute -right-1 -top-1 inline-flex h-4 min-w-4 items-center justify-center rounded-full px-1',
            'bg-accent text-[10px] font-semibold leading-none text-white ring-2 ring-surface'
          )}>
          {badge}
        </span>
      )}
    </NavLink>
  );
}
