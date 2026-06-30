import {formatRelativeTime} from '../query/query.format';
import {cx} from '../../lib/cx';
import type {Notification} from './notifications.types';

type NotificationRowProps = {
  notification: Notification;
  onMarkRead: (id: string) => void;
};

// SPEC-060 FR-003/005: one notification row, rendered as a self-contained card
// (design `.nrow`). Unread rows get a subtle accent wash, a bold message, an
// accent marker dot, and a Mark-read control; read rows are de-emphasized with no
// marker or control (a width-matched slot keeps the message aligned). The unread
// state is also conveyed in a visually-hidden label, so it's never color-only
// (FR-006). There is no delete (notifications are only ever marked read).
export function NotificationRow({notification, onMarkRead}: NotificationRowProps) {
  const {id, message, read, timestamp} = notification;

  return (
    <li
      className={cx(
        'flex items-start gap-3 rounded-md border p-4',
        read ? 'border-border bg-surface' : 'border-[#dfe3fb] bg-accent-soft'
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
          {message}
        </p>
        <p className="mt-1 text-xs text-text-3">{formatRelativeTime(timestamp)}</p>
      </div>

      {!read && (
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
