import {beforeEach, describe, expect, it, vi} from 'vitest';
import {render, screen} from '@testing-library/react';
import {renderWithProviders} from '../test/renderWithProviders';
import {authenticated} from '../test/authFixtures';
import {getNotifications} from '../features/notifications/notifications.service';
import ConnectionsPage from './ConnectionsPage';
import NotificationsPage from './NotificationsPage';
import QueryPage from './QueryPage';

// ─── from ConnectionsPage.test.tsx ───
vi.mock('../features/shared-spaces', () => ({
  ConnectionsPage: () => <div>connections-view</div>
}));

describe('ConnectionsPage', () => {
  // The route component is a thin wrapper: it sets the page title and renders the
  // feature view (covered by features/shared-spaces/ConnectionsPage.test.tsx). Mock
  // the view so this stays a focused smoke test of the wrapper.

  describe('ConnectionsPage route (SPEC-052)', () => {
    it('renders the connections view and sets the document title', () => {
      render(<ConnectionsPage />);
      expect(screen.getByText('connections-view')).toBeInTheDocument();
      expect(document.title).toContain('Connections');
    });
  });
});

// ─── from NotificationsPage.test.tsx ───
vi.mock('../features/notifications/notifications.service', () => ({
  getNotifications: vi.fn(),
  enqueueNotificationAction: vi.fn()
}));

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

// ─── from QueryPage.test.tsx ───
vi.mock('../features/query/SqlEditor', () => ({
  SqlEditor: ({value}: {value: string}) => (
    <textarea
      aria-label="SQL editor"
      defaultValue={value}
    />
  )
}));

vi.mock('aws-amplify/auth', () => ({
  fetchAuthSession: vi.fn().mockRejectedValue(new Error('no session in test'))
}));

describe('QueryPage', () => {
  // The lazy Monaco editor is stubbed to a plain textarea so the route renders
  // without the editor chunk / web workers (react.md §21 "stub the heavy editor by
  // exception"). Amplify is stubbed at the credential boundary so the workspace's
  // data hooks resolve to empty ServiceResults instead of hitting AWS.

  beforeEach(() => {
    vi.clearAllMocks();
    window.innerWidth = 1280;
  });

  describe('QueryPage route', () => {
    it('renders the query workspace for an authenticated user', async () => {
      renderWithProviders(<QueryPage />, {route: '/query', auth: authenticated('alice')});

      // The workspace toolbar is present (real QueryWorkspace, real tab strip).
      expect(await screen.findByRole('button', {name: 'Run statement'})).toBeInTheDocument();
      // The lazy editor mounts (stubbed textarea) once its chunk resolves.
      expect(await screen.findByLabelText('SQL editor')).toBeInTheDocument();
    });

    it('sets the page title', () => {
      renderWithProviders(<QueryPage />, {route: '/query', auth: authenticated('alice')});
      expect(document.title).toMatch(/Query/);
    });
  });
});
