import {beforeEach, describe, expect, it, vi} from 'vitest';
import {screen} from '@testing-library/react';
import {renderWithProviders} from '../test/renderWithProviders';
import {authenticated} from '../test/authFixtures';
import {getNotifications} from '../features/notifications/notifications.service';
import {readSharedConnectionsCache} from '../features/shared-spaces/sharedSpaces.service';
import ConnectionsPage from './ConnectionsPage';
import NotificationsPage from './NotificationsPage';
import QueryPage from './QueryPage';
import {QueryRunsProvider} from '../features/query/QueryRunsProvider';

// ─── from ConnectionsPage.test.tsx ───
vi.mock('../features/shared-spaces/sharedSpaces.service', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../features/shared-spaces/sharedSpaces.service')>()),
  readSharedConnectionsCache: vi.fn()
}));
vi.mock('../lib/idToken', () => ({getIdToken: vi.fn().mockResolvedValue({success: true, data: {}})}));

vi.mock('../features/notifications/notifications.service', () => ({
  getNotifications: vi.fn(),
  enqueueNotificationAction: vi.fn()
}));
// The sanctioned heavy-child exception: Monaco needs a real DOM editor and workers, and jsdom
// has neither, so a textarea stands in for it.
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

describe('ConnectionsPage', () => {
  // The route component is a thin wrapper: it sets the page title and renders the REAL
  // feature view over the one service the view reads on mount. Its behaviour is covered in
  // features/shared-spaces/ConnectionsPage.test.tsx; here only the wiring is asserted.

  describe('ConnectionsPage route (SPEC-052)', () => {
    it('renders the connections view and sets the document title', async () => {
      vi.mocked(readSharedConnectionsCache).mockResolvedValue({success: true, data: {version: 1, connections: []}});
      renderWithProviders(<ConnectionsPage />, {auth: authenticated('alice')});
      expect(await screen.findByRole('heading', {level: 1, name: 'Shared spaces'})).toBeInTheDocument();
      expect(document.title).toContain('Shared spaces');
    });
  });
});

// ─── from NotificationsPage.test.tsx ───

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
      renderWithProviders(
        <QueryRunsProvider username="alice">
          <QueryPage />
        </QueryRunsProvider>,
        {route: '/query', auth: authenticated('alice')}
      );

      // The workspace toolbar is present (real QueryWorkspace, real tab strip).
      expect(await screen.findByRole('button', {name: 'Run statement'})).toBeInTheDocument();
      // The lazy editor mounts (stubbed textarea) once its chunk resolves.
      expect(await screen.findByLabelText('SQL editor')).toBeInTheDocument();
    });

    it('sets the page title', () => {
      renderWithProviders(
        <QueryRunsProvider username="alice">
          <QueryPage />
        </QueryRunsProvider>,
        {route: '/query', auth: authenticated('alice')}
      );
      expect(document.title).toMatch(/Query/);
    });
  });
});
