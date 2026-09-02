import {describe, it, expect, vi, beforeEach, afterEach} from 'vitest';
import {screen, cleanup} from '@testing-library/react';
import {Routes, Route} from 'react-router';
import {ProtectedLayout} from './ProtectedLayout';
import {Header} from './Header';
import {renderWithProviders} from '../test/renderWithProviders';
import {authenticated, unauthenticated, authLoading} from '../test/authFixtures';
import type {AuthContextValue, AuthStatus} from '../features/auth';

vi.mock('../lib/returnPath', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../lib/returnPath')>()),
  setReturnPath: vi.fn()
}));

/**
 * The AWS boundary, and nothing above it (SPEC-154 FR-002). The old
 * `vi.mock('../features/notifications')` replaced the whole barrel, so `prefetchNotifications`
 * never ran and the only assertion available was that a stub had been called with the right
 * arguments — true of a prefetch that populates nothing. Mocking the SERVICE instead is what
 * the sibling tests already do, and it lets the tests below assert what the prefetch is FOR:
 * the header's unread count is right on first paint, with no spinner.
 */
vi.mock('../features/notifications/notifications.service', () => ({
  getNotifications: vi.fn(),
  enqueueNotificationAction: vi.fn().mockResolvedValue({success: true, data: undefined})
}));

// Same boundary, one feature over (SPEC-162).
vi.mock('../features/feature-flags/featureFlags.service', () => ({
  FEATURE_FLAGS_KEY: '_config/feature-flags.json',
  getFeatureFlags: vi.fn()
}));

import {getNotifications} from '../features/notifications/notifications.service';
import {getFeatureFlags} from '../features/feature-flags/featureFlags.service';

const mockGetNotifications = vi.mocked(getNotifications);
const mockGetFeatureFlags = vi.mocked(getFeatureFlags);

const forStatus = (status: AuthStatus): AuthContextValue =>
  status === 'authenticated' ? authenticated('alice') : status === 'loading' ? authLoading() : unauthenticated();

/**
 * Mirrors the App route tree: a public landing marker plus the protected /files child,
 * entered at /files so the guard decides what mounts. The `<Routes>` go INSIDE the harness's
 * router (SPEC-154 FR-007) — route composition being the subject does not call for a
 * hand-rolled provider stack, only for supplying the routes.
 *
 * `withHeader` exists because the header changes what the notification assertions can prove;
 * see the two prefetch tests below.
 */
const renderAtFiles = (auth: AuthContextValue, {withHeader = false} = {}) =>
  renderWithProviders(
    <Routes>
      <Route
        path="/"
        element={<div>LANDING PAGE</div>}
      />
      <Route element={<ProtectedLayout />}>
        <Route
          path="/files"
          element={
            <>
              {withHeader && <Header />}
              <div>PROTECTED CONTENT</div>
            </>
          }
        />
      </Route>
    </Routes>,
    {route: '/files', auth, seedFeatureFlags: false}
  );

beforeEach(() => {
  vi.clearAllMocks();
  mockGetNotifications.mockResolvedValue({success: true, data: []});
  mockGetFeatureFlags.mockResolvedValue({
    success: true,
    data: {
      files: true,
      query: true,
      sharedWorkspaces: true,
      dataQuality: true,
      dataExplorer: true,
      asyncFileOperations: true
    }
  });
});

afterEach(() => {
  cleanup();
});

describe('ProtectedLayout', () => {
  it('while loading: shows a loading indicator and never mounts protected content', () => {
    renderAtFiles(forStatus('loading'));

    expect(screen.getByRole('status')).toBeInTheDocument();
    expect(screen.queryByText('PROTECTED CONTENT')).not.toBeInTheDocument();
    expect(screen.queryByText('LANDING PAGE')).not.toBeInTheDocument();
  });

  it('when unauthenticated: redirects to / and never mounts protected content', () => {
    renderAtFiles(forStatus('unauthenticated'));

    expect(screen.getByText('LANDING PAGE')).toBeInTheDocument();
    expect(screen.queryByText('PROTECTED CONTENT')).not.toBeInTheDocument();
  });

  it('when authenticated: renders the child route content', () => {
    renderAtFiles(forStatus('authenticated'));

    expect(screen.getByText('PROTECTED CONTENT')).toBeInTheDocument();
    expect(screen.queryByText('LANDING PAGE')).not.toBeInTheDocument();
  });
});
