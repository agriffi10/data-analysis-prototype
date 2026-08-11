import {afterEach, describe, expect, it, vi} from 'vitest';
import {cleanup, fireEvent, render, screen} from '@testing-library/react';
import {renderWithProviders} from '../../test/renderWithProviders';
import {MemoryRouter} from 'react-router';
import {NotificationRow} from './NotificationRow';
import {NotificationsBell} from './NotificationsBell';
import {isSafeInAppPath} from './notificationLink';
import type {Notification} from './notifications.types';

// ─── from NotificationRow.test.tsx ───
describe('NotificationRow', () => {
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
      renderWithProviders(
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
      renderWithProviders(
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
      renderWithProviders(
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
      renderWithProviders(
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
      renderWithProviders(
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
      renderWithProviders(
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

    // ── SPEC-113 FR-008: the optional deep link ────────────────────────────────

    // Through the shared harness since SPEC-163: the row drops a link into a DISABLED
    // feature, so it reads the flags and needs the auth context and query client. The harness
    // seeds them all-on, which is the state every assertion below assumes.
    const renderRow = (notification: Notification) =>
      renderWithProviders(
        <ul>
          <NotificationRow
            notification={notification}
            onMarkRead={vi.fn()}
          />
        </ul>
      );

    it('renders the MESSAGE as the link when one is supplied', () => {
      renderRow(note({message: 'Data quality check finished', link: '/data-quality/alice/req-1'}));
      // The accessible name is the message itself — never a trailing "here" — so the
      // anchor says where it goes, and it is keyboard-focusable for free.
      const anchor = screen.getByRole('link', {name: 'Data quality check finished'});
      expect(anchor).toHaveAttribute('href', '/data-quality/alice/req-1');
    });

    it('renders plain text when there is no link — pinning existing notifications unchanged', () => {
      // Table Builder / Table Share / the shared-space verbs supply no link and must be
      // completely unaffected by this field existing.
      renderRow(note());
      expect(screen.queryByRole('link')).not.toBeInTheDocument();
      expect(screen.getByText('Your shared space was created')).toBeInTheDocument();
    });

    it('falls back to plain text for a link that could leave this origin', () => {
      // Rejected AT RENDER, so a notification can never become an open redirect. The
      // protocol-relative and backslash forms are the ones that look like paths.
      for (const link of ['https://evil.test/phish', '//evil.test', '/\\evil.test', 'javascript:alert(1)']) {
        renderRow(note({message: `Suspicious ${link}`, link}));
        expect(screen.queryByRole('link')).not.toBeInTheDocument();
        expect(screen.getByText(`Suspicious ${link}`)).toBeInTheDocument();
        cleanup();
      }
    });
  });
});

// ─── from NotificationsBell.test.tsx ───
describe('NotificationsBell', () => {
  function renderBell(props: {hasUnread: boolean; unreadCount: number}, initialPath = '/files') {
    return render(
      <MemoryRouter initialEntries={[initialPath]}>
        <NotificationsBell {...props} />
      </MemoryRouter>
    );
  }

  afterEach(cleanup);

  describe('NotificationsBell (SPEC-060 FR-001)', () => {
    it('links to /notifications', () => {
      renderBell({hasUnread: false, unreadCount: 0});
      expect(screen.getByRole('link')).toHaveAttribute('href', '/notifications');
    });

    it('conveys the unread count in the accessible name (not color-only)', () => {
      renderBell({hasUnread: true, unreadCount: 3});
      expect(screen.getByRole('link', {name: 'Notifications, 3 unread'})).toBeInTheDocument();
    });

    it('reports none unread when there is nothing unread', () => {
      renderBell({hasUnread: false, unreadCount: 0});
      expect(screen.getByRole('link', {name: 'Notifications, none unread'})).toBeInTheDocument();
    });

    it('shows a numeric count badge (so a 2nd notification is visible, not silent)', () => {
      renderBell({hasUnread: true, unreadCount: 3});
      expect(screen.getByText('3')).toBeInTheDocument();
    });

    it('caps the badge at 9+ for large counts', () => {
      renderBell({hasUnread: true, unreadCount: 12});
      expect(screen.getByText('9+')).toBeInTheDocument();
    });

    it('shows no badge when nothing is unread', () => {
      renderBell({hasUnread: false, unreadCount: 0});
      expect(screen.queryByText('0')).not.toBeInTheDocument();
    });

    it('marks the link current when on /notifications', () => {
      renderBell({hasUnread: false, unreadCount: 0}, '/notifications');
      expect(screen.getByRole('link')).toHaveAttribute('aria-current', 'page');
    });

    it('is not current on other routes', () => {
      renderBell({hasUnread: false, unreadCount: 0}, '/files');
      expect(screen.getByRole('link')).not.toHaveAttribute('aria-current');
    });
  });
});

// ─── from notificationLink.test.ts ───
describe('notificationLink', () => {
  describe('isSafeInAppPath', () => {
    it('accepts an in-app absolute path', () => {
      expect(isSafeInAppPath('/data-quality/alice/req-1')).toBe(true);
      expect(isSafeInAppPath('/files?space=personal&prefix=alice%2Fsales%2F')).toBe(true);
      expect(isSafeInAppPath('/')).toBe(true);
    });

    it('rejects anything that could resolve off this origin', () => {
      // A notification's link is written by a Lambda and read back from S3, then turned
      // into an anchor. Every case below would be an open redirect wearing the app's own
      // chrome, and the last two are the ones a naive `startsWith('//')` check misses.
      expect(isSafeInAppPath('https://evil.test/phish')).toBe(false);
      expect(isSafeInAppPath('http://evil.test')).toBe(false);
      expect(isSafeInAppPath('javascript:alert(1)')).toBe(false);
      expect(isSafeInAppPath('data:text/html,<script>')).toBe(false);
      expect(isSafeInAppPath('//evil.test/phish')).toBe(false); // protocol-relative
      expect(isSafeInAppPath('/\\evil.test/phish')).toBe(false); // backslash authority
      expect(isSafeInAppPath('/\\\\evil.test')).toBe(false);
    });

    it('rejects a relative path, which resolves against whatever route the user is on', () => {
      expect(isSafeInAppPath('data-quality/alice/req-1')).toBe(false);
      expect(isSafeInAppPath('./somewhere')).toBe(false);
      expect(isSafeInAppPath('../somewhere')).toBe(false);
    });

    it('rejects absent and non-string values', () => {
      expect(isSafeInAppPath(undefined)).toBe(false);
      expect(isSafeInAppPath(null)).toBe(false);
      expect(isSafeInAppPath('')).toBe(false);
      expect(isSafeInAppPath(42)).toBe(false);
      expect(isSafeInAppPath({toString: () => '/safe'})).toBe(false);
    });
  });
});
