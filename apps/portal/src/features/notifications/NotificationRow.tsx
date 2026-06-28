import {formatRelativeTime} from '../query/query.format';
import {cx} from '../../lib/cx';
import type {Notification} from './notifications.types';

type NotificationRowProps = {
  notification: Notification;
  onMarkRead: (id: string) => void;
};

// SPEC-060 FR-003/005: one notification row — message, relative timestamp, and an
// unread marker (the same accent-dot language as the active query tab). Unread rows
// carry a Mark-read affordance; read rows are de-emphasized and show no control or
// marker. There is no delete (notifications are only ever marked read).
export function NotificationRow({notification, onMarkRead}: NotificationRowProps) {
  const {id, message, read, timestamp} = notification;

  return (
    <li className={cx('flex items-start gap-3 border-b border-border px-1 py-3 last:border-b-0', read && 'opacity-60')}>
      {/* Unread marker — decorative; the row's unread state is also conveyed in the
          visually-hidden label below, so it's never color-only (FR-006). */}
      <span
        aria-hidden="true"
        className={cx('mt-1.5 h-2 w-2 flex-none rounded-full bg-accent', read && 'invisible')}
      />

      <div className="min-w-0 flex-1">
        <p className="break-words text-sm text-text">
          {!read && <span className="sr-only">Unread: </span>}
          {message}
        </p>
        <p className="mt-0.5 text-xs text-text-3">{formatRelativeTime(timestamp)}</p>
      </div>

      {!read && (
        <button
          type="button"
          onClick={() => onMarkRead(id)}
          className="flex-none rounded-md px-2 py-1 text-xs font-medium text-accent-text hover:bg-surface-2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent">
          Mark read
        </button>
      )}
    </li>
  );
}
