import {NavLink} from 'react-router-dom';
import {BellIcon} from '../../components/icons';
import {cx} from '../../lib/cx';

type NotificationsBellProps = {
  hasUnread: boolean;
  unreadCount: number;
};

// SPEC-060 FR-001: the header notifications control — a react-router link to the
// `/notifications` page (NOT a drawer toggle), sitting left of the username. Shows
// a presence-only accent dot when there are unread notifications (no numeric badge
// in v1); the count is carried in the accessible name so the indicator is never
// color-only (FR-006). NavLink supplies the active/current state on `/notifications`.
export function NotificationsBell({hasUnread, unreadCount}: NotificationsBellProps) {
  const label = hasUnread ? `Notifications, ${unreadCount} unread` : 'Notifications, none unread';

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
        // Presence-only dot (same accent language as the active query tab). The
        // count lives in the link's aria-label, so this is decorative.
        <span
          aria-hidden="true"
          className="absolute right-1.5 top-1.5 h-2 w-2 rounded-full bg-accent ring-2 ring-surface"
        />
      )}
    </NavLink>
  );
}
