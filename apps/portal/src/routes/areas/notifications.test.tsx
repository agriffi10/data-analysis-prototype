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
    renderApp('/notifications', {auth: authenticated('alice')});

    expect(await screen.findByText('You’re all caught up')).toBeInTheDocument();
    expect(screen.getByRole('link', {name: 'Files'})).toBeInTheDocument();
  });
});

/**
 * Wait until the page settles on the area's own content or on the not-found page, then fail naming
 * the not-found page if that is what rendered: Next renders it for an area page missing from disk.
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

  // The page as it stands on disk: with it deleted, Next renders the not-found page at its path.
  it('is served by its own page, where Next would render the not-found page without it', async () => {
    vi.mocked(getNotifications).mockResolvedValue({success: true, data: []});
    renderApp('/notifications', {auth: authenticated('alice')});

    await servedByItsPage(() => screen.queryByRole('heading', {name: 'Notifications', level: 1}));
  });

  it('follows a link to a report, through Next’s router to the report’s page', async () => {
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
    const {user} = renderApp('/notifications', {auth: authenticated('alice')});

    await user.click(await screen.findByRole('link', {name: 'Your data-quality report is ready'}));

    expect(await screen.findByRole('heading', {name: 'Report alice req-1'})).toBeInTheDocument();
    expect(requests()).toEqual(['/data-quality/alice/req-1']);
  });
});
