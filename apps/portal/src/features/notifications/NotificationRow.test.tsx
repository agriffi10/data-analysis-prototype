import {describe, it, expect, vi, afterEach} from 'vitest';
import {render, screen, cleanup, fireEvent} from '@testing-library/react';
import {NotificationRow} from './NotificationRow';
import type {Notification} from './notifications.types';

const note = (over: Partial<Notification> = {}): Notification => ({
  id: 'n1',
  message: 'Your shared space was created',
  read: false,
  timestamp: new Date(Date.now() - 60_000).toISOString(),
  ...over
});

function setWidth(w: number) {
  Object.defineProperty(window, 'innerWidth', {value: w, writable: true, configurable: true});
}

afterEach(() => {
  cleanup();
  setWidth(1024);
});

describe('NotificationRow (SPEC-060 FR-003/005)', () => {
  it('renders message, a relative timestamp, and a Mark-read control on unread rows', () => {
    render(
      <ul>
        <NotificationRow
          notification={note()}
          onMarkRead={vi.fn()}
        />
      </ul>
    );
    expect(screen.getByText('Your shared space was created')).toBeInTheDocument();
    expect(screen.getByText(/min ago/)).toBeInTheDocument();
    expect(screen.getByRole('button', {name: 'Mark read'})).toBeInTheDocument();
  });

  it('conveys unread state non-visually', () => {
    render(
      <ul>
        <NotificationRow
          notification={note()}
          onMarkRead={vi.fn()}
        />
      </ul>
    );
    expect(screen.getByText('Unread:')).toBeInTheDocument();
  });

  it('read rows are de-emphasized and have no Mark-read control', () => {
    render(
      <ul>
        <NotificationRow
          notification={note({read: true})}
          onMarkRead={vi.fn()}
        />
      </ul>
    );
    expect(screen.queryByRole('button', {name: 'Mark read'})).not.toBeInTheDocument();
    expect(screen.queryByText('Unread:')).not.toBeInTheDocument();
  });

  it('calls onMarkRead with the id when clicked', () => {
    const onMarkRead = vi.fn();
    render(
      <ul>
        <NotificationRow
          notification={note({id: 'abc'})}
          onMarkRead={onMarkRead}
        />
      </ul>
    );
    fireEvent.click(screen.getByRole('button', {name: 'Mark read'}));
    expect(onMarkRead).toHaveBeenCalledWith('abc');
  });

  // ── SPEC-102: responsive Mark-read placement ───────────────────────────────

  it('renders Mark-read as a compact trailing control at ≥ tablet', () => {
    setWidth(1024);
    render(
      <ul>
        <NotificationRow
          notification={note()}
          onMarkRead={vi.fn()}
        />
      </ul>
    );
    const button = screen.getByRole('button', {name: 'Mark read'});
    expect(button).toHaveClass('flex-none');
    expect(button).not.toHaveClass('w-full');
  });

  it('renders Mark-read as a full-width 34px button below the message on mobile', () => {
    setWidth(400);
    render(
      <ul>
        <NotificationRow
          notification={note()}
          onMarkRead={vi.fn()}
        />
      </ul>
    );
    const button = screen.getByRole('button', {name: 'Mark read'});
    expect(button).toHaveClass('w-full', 'h-[34px]');
    // It sits inside the message column, after the timestamp.
    expect(button.previousElementSibling).toHaveTextContent(/min ago/);
    // Only one Mark-read control exists (mount-gated, not duplicated).
    expect(screen.getAllByRole('button', {name: 'Mark read'})).toHaveLength(1);
  });
});
