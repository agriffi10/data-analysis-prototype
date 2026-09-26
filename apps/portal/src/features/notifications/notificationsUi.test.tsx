import {afterEach, describe, expect, it, vi} from 'vitest';
import {cleanup, fireEvent, render, screen} from '@testing-library/react';
import {renderWithProviders} from '../../test/renderWithProviders';
import {COMPONENT_AXE_OPTIONS, expectContainerHasNoA11yViolations} from '../../test/axe';
import {MemoryRouter} from 'react-router';
import {NotificationRow} from './NotificationRow';
import {NotificationsBell} from './NotificationsBell';
import {isSafeInAppPath, reviewHref} from './notificationLink';
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

    it('shows a numeric count badge (so a 2nd notification is visible, not silent)', () => {
      renderBell({hasUnread: true, unreadCount: 3});
      expect(screen.getByText('3')).toBeInTheDocument();
    });

    it('caps the badge at 9+ for large counts', () => {
      renderBell({hasUnread: true, unreadCount: 12});
      expect(screen.getByText('9+')).toBeInTheDocument();
    });

    it('marks the link current when on /notifications', () => {
      renderBell({hasUnread: false, unreadCount: 0}, '/notifications');
      expect(screen.getByRole('link')).toHaveAttribute('aria-current', 'page');
    });
  });
});

// ─── from notificationLink.test.ts ───
describe('the review-conflicts action on a row', () => {
  const conflicted = (over: Partial<Notification> = {}): Notification => ({
    id: 'n9',
    message: 'Moved 1 of 2 items to "out". 1 was not moved: "q1.csv" - something is in the way.',
    read: false,
    timestamp: new Date(Date.now() - 60_000).toISOString(),
    link: '/files?space=finance&prefix=finance/out/',
    payload: {
      requestId: '11111111-2222-3333-4444-555555555555',
      operation: 'move',
      conflicts: [{itemKey: 'alice/q1.csv', kind: 'file'}]
    },
    ...over
  });

  afterEach(cleanup);

  function rowFor(notification: Notification) {
    renderWithProviders(
      <ul>
        <NotificationRow
          notification={notification}
          onMarkRead={vi.fn()}
        />
      </ul>
    );
  }

  it('is a SIBLING of the message anchor, never nested inside it', () => {
    // The row deliberately makes the whole message the link, to keep it a single target with an
    // accessible name that says where it goes. An interactive control inside that anchor is
    // `nested-interactive` — an axe failure this repo has shipped twice.
    rowFor(conflicted());
    const message = screen.getByRole('link', {name: /Moved 1 of 2 items/});
    const review = screen.getByRole('link', {name: 'Review conflicts'});

    expect(message.contains(review)).toBe(false);
    expect(review.closest('a')).toBe(review);
  });

  it('carries the request id into the row own destination without inventing a separator', () => {
    // The base already carries `?space=`, which is where a hand-rolled `?` produces a URL nobody
    // validated. Read back through URLSearchParams rather than string-matched, so the assertion
    // is about what the browser will parse.
    rowFor(conflicted());
    const href = screen.getByRole('link', {name: 'Review conflicts'}).getAttribute('href')!;
    const params = new URLSearchParams(href.split('?')[1]);

    expect(href.startsWith('/files?')).toBe(true);
    expect(params.get('requestId')).toBe('11111111-2222-3333-4444-555555555555');
    expect(params.get('space')).toBe('finance');
    expect(params.get('prefix')).toBe('finance/out/');
  });

  it('still offers the action when the notification carries no usable link', () => {
    // Reachability of the conflicts must not depend on a PREFIX link, which is a strictly more
    // failure-prone thing than the request id the view actually needs — and a user who closed the
    // submitting tab has nowhere else to go.
    rowFor(conflicted({link: undefined}));
    const href = screen.getByRole('link', {name: 'Review conflicts'}).getAttribute('href')!;

    expect(href.startsWith('/files?')).toBe(true);
    expect(new URLSearchParams(href.split('?')[1]).get('requestId')).toBe('11111111-2222-3333-4444-555555555555');
  });

  it('has no axe violations, against the container the row is actually rendered in', async () => {
    // The DRIVEN container, not a re-render: `expectNoA11yViolations` mounts the element it is
    // handed a second time, which for a row whose action depends on provider state would check a
    // tree the user never sees. `renderWithProviders` is also what supplies the feature flags the
    // gate reads — a bare router throws before axe ever runs.
    const {container} = renderWithProviders(
      <ul>
        <NotificationRow
          notification={conflicted()}
          onMarkRead={vi.fn()}
        />
      </ul>
    );
    expect(screen.getByRole('link', {name: 'Review conflicts'})).toBeInTheDocument();

    await expectContainerHasNoA11yViolations(container, COMPONENT_AXE_OPTIONS);
  });
});

describe('reviewHref', () => {
  it('falls back to the file browser when the row resolved no link', () => {
    expect(reviewHref(undefined, 'r-3').startsWith('/files?')).toBe(true);
  });
});

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
      // Control characters the URL parser strips, leaving a protocol-relative path behind.
      expect(isSafeInAppPath('/\t/evil.test')).toBe(false);
      expect(isSafeInAppPath('/\n/evil.test')).toBe(false);
      expect(isSafeInAppPath('/\r\\evil.test')).toBe(false);
      // Refused for the character itself, though this one would resolve on this origin.
      expect(isSafeInAppPath('/files\u0000')).toBe(false);
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
