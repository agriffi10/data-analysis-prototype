import {beforeEach, describe, expect, it, vi} from 'vitest';
import {screen, waitFor} from '@testing-library/react';
import {renderApp} from '../../test/appRouter';
import {renderWithProviders} from '../../test/renderWithProviders';
import {authenticated} from '../../test/authFixtures';
import {enqueueNotificationAction, getNotifications} from '../../features/notifications/notifications.service';
import {requests} from '../../test/nextNavigation';
import NotificationsPage from '../NotificationsPage';

vi.mock('../../features/notifications/notifications.service', () => ({
  getNotifications: vi.fn(),
  enqueueNotificationAction: vi.fn()
}));
vi.mock('aws-amplify/auth', () => ({
  fetchAuthSession: vi.fn().mockRejectedValue(new Error('no session in test'))
}));
// The report, standing in for the page a notification links to: it shows the params it was
// reached with, which is what the link decides. Its services are not this file's subject.
vi.mock('../DataQualityReportPage', async () => {
  const navigation = await import('../../lib/navigation');
  return {
    default: function DataQualityReportStandIn() {
      const {space, requestId} = navigation.useParams();
      return <h1>{`Report ${space} ${requestId}`}</h1>;
    }
  };
});

describe('NotificationsPage', () => {
  // Thin route wrapper around the notifications feature page. Render the real
  // feature (real useNotifications) over a mocked read boundary — the only AWS
  // touchpoint is `getNotifications`.

  const mockGet = vi.mocked(getNotifications);

  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe('NotificationsPage route', () => {
    it('renders the empty state when the inbox has no notifications', async () => {
      mockGet.mockResolvedValue({success: true, data: []});

      renderWithProviders(<NotificationsPage />, {route: '/notifications', auth: authenticated('alice')});

      expect(await screen.findByText('You’re all caught up')).toBeInTheDocument();
      expect(screen.getByRole('heading', {name: 'Notifications'})).toBeInTheDocument();
    });

    it('renders a notification from the inbox', async () => {
      mockGet.mockResolvedValue({
        success: true,
        data: [{id: 'n1', message: 'Bob shared a space with you', read: false, timestamp: '2026-07-09T00:00:00Z'}]
      });

      renderWithProviders(<NotificationsPage />, {route: '/notifications', auth: authenticated('alice')});

      expect(await screen.findByText('Bob shared a space with you')).toBeInTheDocument();
    });
  });
});

describe('the notifications area', () => {
  it('serves /notifications inside the shell', async () => {
    vi.mocked(getNotifications).mockResolvedValue({success: true, data: []});
    renderApp('/notifications', {auth: authenticated('alice'), routers: {notifications: 'app'}});

    expect(await screen.findByText('You’re all caught up')).toBeInTheDocument();
    expect(screen.getByRole('link', {name: 'Files'})).toBeInTheDocument();
  });
});

/**
 * Wait until the page settles on the area's own content or on the catch-all's 404, then fail naming
 * the 404 if that is what rendered: an area page missing from disk falls through to it.
 */
async function servedByItsPage(content: () => HTMLElement | null) {
  const notFound = () => screen.queryByRole('heading', {name: 'Page not found'});
  await waitFor(() => expect(content() ?? notFound()).not.toBeNull());
  expect(notFound()).not.toBeInTheDocument();
  expect(content()).toBeInTheDocument();
}

describe('Notifications on the App Router', () => {
  beforeEach(() => {
    vi.mocked(enqueueNotificationAction).mockResolvedValue({success: true, data: undefined});
  });

  // The records and the pages as they stand: with the page deleted, the record still says 'app', so
  // the catch-all no longer builds the route and renders the 404.
  it('is served by its own page, where the catch-all would render the 404', async () => {
    vi.mocked(getNotifications).mockResolvedValue({success: true, data: []});
    renderApp('/notifications', {auth: authenticated('alice'), routers: 'as-recorded'});

    await servedByItsPage(() => screen.queryByRole('heading', {name: 'Notifications', level: 1}));
  });

  // Data quality is named for each router in turn, so the link is proved across the two routers and
  // between two App Router pages.
  it.each(['catch-all', 'app'] as const)('follows a link to a report the %s serves', async (router) => {
    vi.mocked(getNotifications).mockResolvedValue({
      success: true,
      data: [
        {
          id: 'n2',
          message: 'Your data-quality report is ready',
          read: false,
          timestamp: '2026-11-14T00:00:00Z',
          link: '/data-quality/alice/req-1'
        }
      ]
    });
    const {user} = renderApp('/notifications', {
      auth: authenticated('alice'),
      routers: {notifications: 'app', 'data-quality': router}
    });

    await user.click(await screen.findByRole('link', {name: 'Your data-quality report is ready'}));

    expect(await screen.findByRole('heading', {name: 'Report alice req-1'})).toBeInTheDocument();
    expect(requests()).toEqual(['/data-quality/alice/req-1']);
  });
});
