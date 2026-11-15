import {beforeEach, describe, expect, it, vi} from 'vitest';
import {act, screen, waitFor} from '@testing-library/react';
import {renderApp} from '../../test/appRouter';
import {renderWithProviders} from '../../test/renderWithProviders';
import {authenticated} from '../../test/authFixtures';
import {wrappersOf} from '../../test/viewSource';
import {requests} from '../../test/nextNavigation';
import {readSharedConnectionsCache} from '../../features/shared-spaces/sharedSpaces.service';
import ConnectionsPage from '../ConnectionsPage';

vi.mock('../../features/shared-spaces/sharedSpaces.service', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../features/shared-spaces/sharedSpaces.service')>()),
  readSharedConnectionsCache: vi.fn()
}));

// Below this line, what the App Router's Connections page is proved with. The shell's one other
// call is mocked at its boundary, so nothing here leans on the Amplify or token mocks above.
vi.mock('../../features/notifications/notifications.service', () => ({
  getNotifications: vi.fn().mockResolvedValue({success: true, data: []}),
  enqueueNotificationAction: vi.fn().mockResolvedValue({success: true, data: undefined})
}));

/** How many times the Connections page has rendered: a pass-through, so the real page still renders. */
const connectionsPage = vi.hoisted(() => ({renders: 0}));
vi.mock('../ConnectionsPage', async (importOriginal) => {
  const {createElement} = await import('react');
  const actual = await importOriginal<typeof import('../ConnectionsPage')>();
  return {
    default: function CountedConnectionsPage() {
      connectionsPage.renders += 1;
      return createElement(actual.default);
    }
  };
});

const VIEW = Object.values(
  import.meta.glob('./connections.tsx', {query: '?raw', import: 'default', eager: true})
)[0] as string;

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

describe('the connections area', () => {
  it('serves /connections inside the shell', async () => {
    vi.mocked(readSharedConnectionsCache).mockResolvedValue({success: true, data: {version: 1, connections: []}});
    renderApp('/connections', {auth: authenticated('alice'), routers: {connections: 'app'}});

    expect(await screen.findByRole('heading', {level: 1, name: 'Shared spaces'})).toBeInTheDocument();
    expect(screen.getByRole('link', {name: 'Files'})).toBeInTheDocument();
  });

  it('wraps the page in FeatureRoute → ErrorBoundary → Suspense, in that order, behind the shared-workspaces flag', () => {
    expect(wrappersOf(VIEW, 'ConnectionsPage')).toEqual(['FeatureRoute', 'ErrorBoundary', 'Suspense']);
    expect(VIEW).toContain('<FeatureRoute flag="sharedWorkspaces">');
  });
});

// ─── served by the App Router ───

describe('the Connections page on the App Router', () => {
  beforeEach(() => {
    connectionsPage.renders = 0;
    vi.mocked(readSharedConnectionsCache).mockResolvedValue({success: true, data: {version: 1, connections: []}});
  });

  it('is served by its own page: its tab goes through Next’s router, and the page shows its heading', async () => {
    // Help pinned to the catch-all, so the request below is the Connections router speaking, not Help's.
    const {user} = renderApp('/help', {auth: authenticated('alice'), routers: {help: 'catch-all', connections: 'app'}});

    await user.click(await screen.findByRole('link', {name: 'Shared spaces'}));

    // Its own page or the catch-all's 404 in its place, whichever renders first; only its own passes.
    const own = () => screen.queryByRole('heading', {level: 1, name: 'Shared spaces'});
    await waitFor(() => expect(own() ?? screen.queryByRole('heading', {name: 'Page not found'})).not.toBeNull());
    expect(screen.queryByRole('heading', {name: 'Page not found'})).not.toBeInTheDocument();
    expect(own()).toBeInTheDocument();
    expect(requests()).toEqual(['/connections']);
    // The counter reaches the page the view loads, so the flag-off test's zero means something.
    expect(connectionsPage.renders).toBeGreaterThan(0);
  });

  it('shows the unavailable page with shared workspaces off, and never renders the Connections page', async () => {
    renderApp('/connections', {
      auth: authenticated('alice'),
      routers: {connections: 'app'},
      featureFlags: {sharedWorkspaces: false}
    });

    expect(await screen.findByRole('heading', {name: 'Shared spaces isn’t available'})).toBeInTheDocument();
    // The page's module has resolved, so a render the gate let through has happened by now.
    await act(() => import('../ConnectionsPage'));
    expect(connectionsPage.renders).toBe(0);
  });
});
