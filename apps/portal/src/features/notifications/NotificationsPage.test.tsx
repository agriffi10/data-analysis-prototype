import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';
import {cleanup, render, screen, waitFor, within} from '@testing-library/react';
import {TestProviders, renderWithProviders} from '../../test/renderWithProviders';
import {DataQualityReportPage} from '../data-quality/DataQualityReportPage';
import {NotificationsPage} from './NotificationsPage';
import {enqueueNotificationAction, getNotifications} from './notifications.service';
import {QueryClient} from '@tanstack/react-query';
import {authValue} from '../../test/authFixtures';
import {ROUTE_AXE_OPTIONS, expectNoA11yViolations} from '../../test/axe';
import {NotificationsBell} from './NotificationsBell';
import type {Notification} from './notifications.types';
import type {ReactElement, ReactNode} from 'react';
import {AREAS} from '../../lib/navigation';

// ─── from NotificationsPage.test.tsx ───
vi.mock('../data-quality/dataQualityReport.service', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../data-quality/dataQualityReport.service')>()),
  getQualityReport: vi.fn().mockResolvedValue({success: false, error: {message: 'not found'}})
}));

vi.mock('./notifications.service', () => ({
  getNotifications: vi.fn(),
  enqueueNotificationAction: vi.fn()
}));

describe('NotificationsPage', () => {
  // Integration style (react.md §21): render the REAL NotificationsPage with its real
  // hooks (useNotifications, usePageTitle) and real children (NotificationRow, Pager,
  // filter tabs). Mock ONLY the AWS boundary — the notifications service (S3 read +
  // SQS enqueue). Auth + router + QueryClient come from the shared harness.
  // The report page the deep link lands on reads its own S3 boundary; stub it so this test is
  // about ROUTING, not about the report.

  const mockGet = vi.mocked(getNotifications);
  const mockEnqueue = vi.mocked(enqueueNotificationAction);

  const list = (n: number, opts: {read?: boolean} = {}): Notification[] =>
    Array.from({length: n}, (_, i) => ({
      id: `n${i}`,
      message: `Message ${i}`,
      read: opts.read ?? false,
      // newest-first: index 0 is the most recent
      timestamp: new Date(2026, 5, 28, 0, n - i).toISOString()
    }));

  const renderPage = () => renderWithProviders(<NotificationsPage />);

  beforeEach(() => {
    mockEnqueue.mockResolvedValue({success: true, data: undefined});
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  describe('NotificationsPage (SPEC-060)', () => {
    it('shows the loading state, then the list under a mobile-stacked page header', async () => {
      mockGet.mockResolvedValue({success: true, data: list(3)});
      renderPage();
      expect(screen.getByText('Loading notifications…')).toBeInTheDocument();
      await waitFor(() => expect(screen.getByText('Message 0')).toBeInTheDocument());
      // The PageLayout header stacks below tablet, inline at ≥ tablet (SPEC-102 FR-002).
      const header = screen.getByRole('heading', {level: 1, name: 'Notifications'}).closest('div')!.parentElement!;
      expect(header).toHaveClass('flex-col', 'tablet:flex-row');
    });

    it('shows the empty state when there are no notifications', async () => {
      mockGet.mockResolvedValue({success: true, data: []});
      renderPage();
      await waitFor(() => expect(screen.getByText('You’re all caught up')).toBeInTheDocument());
    });

    it('shows an error state with a retry that re-reads', async () => {
      mockGet.mockResolvedValueOnce({success: false, error: {message: 'boom'}});
      const {user} = renderPage();
      await waitFor(() => expect(screen.getByText('Couldn’t load notifications.')).toBeInTheDocument());

      mockGet.mockResolvedValue({success: true, data: list(1)});
      await user.click(screen.getByRole('button', {name: 'Try again'}));
      await waitFor(() => expect(screen.getByText('Message 0')).toBeInTheDocument());
    });

    it('paginates 10 per page, newest-first, with an accurate range label', async () => {
      mockGet.mockResolvedValue({success: true, data: list(25)});
      const {user} = renderPage();
      await waitFor(() => expect(screen.getByText('Message 0')).toBeInTheDocument());

      expect(screen.getByText(/1–10 of 25/)).toBeInTheDocument();
      expect(screen.queryByText('Message 10')).not.toBeInTheDocument();
      expect(screen.getByRole('button', {name: 'Prev'})).toBeDisabled();

      await user.click(screen.getByRole('button', {name: 'Next'}));
      expect(screen.getByText(/11–20 of 25/)).toBeInTheDocument();
      expect(screen.getByText('Message 10')).toBeInTheDocument();
    });

    it('mark read enqueues and optimistically clears just that row marker', async () => {
      mockGet.mockResolvedValue({success: true, data: list(2)});
      const {user} = renderPage();
      await waitFor(() => expect(screen.getAllByRole('button', {name: 'Mark read'})).toHaveLength(2));

      const firstRow = screen.getByText('Message 0').closest('li')!;
      await user.click(within(firstRow).getByRole('button', {name: 'Mark read'}));

      await waitFor(() => expect(mockEnqueue).toHaveBeenCalledWith({action: 'markRead', username: 'alice', id: 'n0'}));
      await waitFor(() => expect(screen.getAllByRole('button', {name: 'Mark read'})).toHaveLength(1));
    });

    it('mark all read enqueues, clears every marker, and leaves the control disabled once nothing is unread', async () => {
      mockGet.mockResolvedValue({success: true, data: list(3)});
      const {user} = renderPage();
      await waitFor(() => expect(screen.getAllByRole('button', {name: 'Mark read'})).toHaveLength(3));

      const markAll = screen.getByRole('button', {name: 'Mark all read'});
      expect(markAll).toBeEnabled();
      await user.click(markAll);

      await waitFor(() => expect(mockEnqueue).toHaveBeenCalledWith({action: 'markAllRead', username: 'alice'}));
      await waitFor(() => expect(screen.queryByRole('button', {name: 'Mark read'})).not.toBeInTheDocument());
      expect(markAll).toBeDisabled();
    });

    it('rolls back and shows a danger toast when an action fails', async () => {
      mockGet.mockResolvedValue({success: true, data: list(1)});
      mockEnqueue.mockResolvedValue({success: false, error: {message: 'queue down', code: 'NetworkError'}});
      const {user} = renderPage();
      await waitFor(() => expect(screen.getByRole('button', {name: 'Mark read'})).toBeInTheDocument());

      await user.click(screen.getByRole('button', {name: 'Mark read'}));

      // The danger toast shows FR-001-mapped text, not the raw 'queue down'.
      await waitFor(() => expect(screen.getByText(/Check your connection/)).toBeInTheDocument());
      expect(screen.queryByText('queue down')).not.toBeInTheDocument();
      // rolled back — the unread row (and its Mark read control) is still present.
      expect(screen.getByRole('button', {name: 'Mark read'})).toBeInTheDocument();
    });

    it('the Unread filter hides read notifications and re-pages the list', async () => {
      mockGet.mockResolvedValue({
        success: true,
        data: [
          {id: 'u', message: 'Unread one', read: false, timestamp: '2026-06-28T00:02:00.000Z'},
          {id: 'r', message: 'Read one', read: true, timestamp: '2026-06-28T00:01:00.000Z'}
        ]
      });
      const {user} = renderPage();
      await waitFor(() => expect(screen.getByText('Read one')).toBeInTheDocument());
      expect(screen.getByText(/1–2 of 2/)).toBeInTheDocument();

      await user.click(screen.getByRole('button', {name: /^unread$/i}));
      expect(screen.queryByText('Read one')).not.toBeInTheDocument();
      expect(screen.getByText('Unread one')).toBeInTheDocument();
      expect(screen.getByText(/1–1 of 1/)).toBeInTheDocument();
      expect(screen.getByRole('button', {name: /^unread$/i})).toHaveAttribute('aria-pressed', 'true');
    });

    it('shows "No unread notifications." when the Unread filter has nothing (and Mark all read is disabled)', async () => {
      mockGet.mockResolvedValue({success: true, data: list(2, {read: true})});
      const {user} = renderPage();
      await waitFor(() => expect(screen.getByText('Message 0')).toBeInTheDocument());
      expect(screen.getByRole('button', {name: 'Mark all read'})).toBeDisabled();

      await user.click(screen.getByRole('button', {name: /^unread$/i}));
      expect(screen.getByText('No unread notifications.')).toBeInTheDocument();
      expect(screen.queryByText('Message 0')).not.toBeInTheDocument();
    });
  });

  // ── SPEC-154 FR-006: a notification's link is FOLLOWED, not just inspected ──
  //
  // The links are LAMBDA-AUTHORED (SPEC-114 mints them server-side), and the only assertion on
  // them was `toHaveAttribute('href', '/data-quality/alice/req-1')` — which pins the string a
  // producer emits against the string a test hard-codes, and says nothing about whether the
  // app's route table still matches it. Rename the route and both stay green while every
  // notification link in production 404s.
  describe('NotificationsPage — following a notification link (SPEC-114)', () => {
    it('lands on the report route the link names', async () => {
      mockGet.mockResolvedValue({
        success: true,
        data: [
          {
            id: 'n1',
            message: 'Data quality check finished',
            read: false,
            timestamp: '2026-06-28T00:00:00.000Z',
            link: '/data-quality/alice/req-1'
          }
        ]
      });

      // The report's real pattern, so the link is resolved by the matcher the app ships.
      const {user} = renderWithProviders(<NotificationsPage />, {
        route: '/notifications',
        path: '/notifications',
        routes: {'/data-quality/:space/:requestId': <DataQualityReportPage />}
      });

      await user.click(await screen.findByRole('link', {name: /Data quality check finished/}));

      // The report page renders — which is only possible if the link's shape and the route's
      // pattern still agree. Its own content is the report page's subject, not this test's.
      expect(await screen.findByRole('heading', {name: /data quality/i})).toBeInTheDocument();
      expect(screen.queryByText('Message 0')).not.toBeInTheDocument();
    });

    it('uses the pattern the app actually routes on', () => {
      // GUARDS THE TEST ABOVE, which declares both the link and the route and so would keep
      // agreeing with itself after a rename. The area records are the third party: read them
      // as data and require the pattern this file exercises to be one the app really serves.
      expect(AREAS.flatMap((record) => record.paths)).toContain('/data-quality/:space/:requestId');
    });
  });
});

// ─── from NotificationsPage.a11y.test.tsx ───

describe('NotificationsPage.a11y', () => {
  // Integration style: render the REAL page/bell with real hooks + children; mock only
  // the AWS boundary (the notifications service). Auth is provided via the real
  // AuthContext (never mocked), matching the rest of the suite.

  // Bespoke tree, kept deliberately (SPEC-154 FR-007): `expectNoA11yViolations` takes a
  // COMPOSED ELEMENT and renders it itself, so there is no `renderWithProviders` result to
  // hand it. The client is bespoke too, and that is load-bearing: the pattern below warms
  // the cache in one render and reuses it in the next, which `createTestQueryClient`'s
  // `gcTime: 0` would defeat — axe would then inspect a loading state and pass vacuously.
  const mockGet = vi.mocked(getNotifications);

  const data: Notification[] = [
    {id: 'a', message: 'Shared space “sales” created', read: false, timestamp: '2026-06-28T00:02:00.000Z'},
    {id: 'b', message: 'You were added to “ops”', read: true, timestamp: '2026-06-28T00:01:00.000Z'}
  ];

  // One QueryClient per element (default gcTime) so the render inside
  // `expectNoA11yViolations` reuses the cache warmed by the preceding render — axe then
  // runs against the populated list, not the loading state.
  function withProviders(ui: ReactNode): ReactElement {
    const client = new QueryClient({defaultOptions: {queries: {retry: false}}});
    return (
      <TestProviders
        auth={authValue()}
        queryClient={client}
        seedFeatureFlags={false}>
        {ui}
      </TestProviders>
    );
  }

  beforeEach(() => {
    mockGet.mockResolvedValue({success: true, data});
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  describe('NotificationsPage accessibility (SPEC-060 FR-006)', () => {
    it('has no axe violations with a populated list', async () => {
      const ui = withProviders(<NotificationsPage />);
      render(ui);
      await waitFor(() => expect(screen.getByText('Shared space “sales” created')).toBeInTheDocument());
      cleanup();
      await expectNoA11yViolations(ui, ROUTE_AXE_OPTIONS);
    });

    it('has no axe violations at a mobile width (stacked header + full-width Mark-read) [SPEC-102 FR-005]', async () => {
      Object.defineProperty(window, 'innerWidth', {value: 400, writable: true, configurable: true});
      const ui = withProviders(<NotificationsPage />);
      render(ui);
      await waitFor(() => expect(screen.getByText('Shared space “sales” created')).toBeInTheDocument());
      cleanup();
      await expectNoA11yViolations(ui, ROUTE_AXE_OPTIONS);
    });

    it('exposes exactly one <h1> and a <main> landmark', async () => {
      render(withProviders(<NotificationsPage />));
      await waitFor(() => expect(screen.getByText('Shared space “sales” created')).toBeInTheDocument());
      expect(screen.getAllByRole('heading', {level: 1})).toHaveLength(1);
      expect(screen.getByRole('main')).toBeInTheDocument();
    });

    it('the header bell has no axe violations', async () => {
      await expectNoA11yViolations(
        withProviders(
          <NotificationsBell
            hasUnread
            unreadCount={2}
          />
        )
      );
    });
  });
});
