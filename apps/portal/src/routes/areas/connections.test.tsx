import {describe, expect, it, vi} from 'vitest';
import {screen} from '@testing-library/react';
import {renderApp} from '../../test/appRouter';
import {renderWithProviders} from '../../test/renderWithProviders';
import {authenticated} from '../../test/authFixtures';
import {wrappersOf} from '../../test/viewSource';
import {readSharedConnectionsCache} from '../../features/shared-spaces/sharedSpaces.service';
import ConnectionsPage from '../ConnectionsPage';

vi.mock('../../features/shared-spaces/sharedSpaces.service', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../features/shared-spaces/sharedSpaces.service')>()),
  readSharedConnectionsCache: vi.fn()
}));
vi.mock('../../lib/idToken', () => ({getIdToken: vi.fn().mockResolvedValue({success: true, data: {}})}));
vi.mock('aws-amplify/auth', () => ({
  fetchAuthSession: vi.fn().mockRejectedValue(new Error('no session in test'))
}));

const VIEW = Object.values(import.meta.glob('./connections.tsx', {query: '?raw', import: 'default', eager: true}))[0] as string;

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
    renderApp('/connections', {auth: authenticated('alice')});

    expect(await screen.findByRole('heading', {level: 1, name: 'Shared spaces'})).toBeInTheDocument();
    expect(screen.getByRole('link', {name: 'Files'})).toBeInTheDocument();
  });

  it('wraps the page in FeatureRoute → ErrorBoundary → Suspense, in that order, behind the shared-workspaces flag', () => {
    expect(wrappersOf(VIEW, 'ConnectionsPage')).toEqual(['FeatureRoute', 'ErrorBoundary', 'Suspense']);
    expect(VIEW).toContain('<FeatureRoute flag="sharedWorkspaces">');
  });
});
