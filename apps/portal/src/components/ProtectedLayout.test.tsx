import {describe, it, expect, vi, beforeEach, afterEach, type MockedFunction} from 'vitest';
import {screen, cleanup, waitFor} from '@testing-library/react';
import {Routes, Route} from 'react-router';
import {ProtectedLayout} from './ProtectedLayout';
import {Header} from './Header';
import {renderWithProviders} from '../test/renderWithProviders';
import {authenticated, unauthenticated, authLoading} from '../test/authFixtures';
import type {AuthContextValue, AuthStatus} from '../features/auth';

vi.mock('../lib/returnPath', () => ({setReturnPath: vi.fn()}));

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

import {setReturnPath} from '../lib/returnPath';
import {getNotifications} from '../features/notifications/notifications.service';
import {getFeatureFlags} from '../features/feature-flags/featureFlags.service';

const mockGetNotifications = vi.mocked(getNotifications);
const mockGetFeatureFlags = vi.mocked(getFeatureFlags);
const mockSetReturnPath = setReturnPath as unknown as MockedFunction<(path: string) => void>;

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
    {route: '/files', auth}
  );

beforeEach(() => {
  vi.clearAllMocks();
  mockGetNotifications.mockResolvedValue({success: true, data: []});
  mockGetFeatureFlags.mockResolvedValue({
    success: true,
    data: {files: true, query: true, sharedWorkspaces: true, dataQuality: true}
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

  it('when unauthenticated: stores the attempted path as the return path', () => {
    renderAtFiles(forStatus('unauthenticated'));

    expect(mockSetReturnPath).toHaveBeenCalledWith('/files');
  });

  it('when authenticated: renders the child route content', () => {
    renderAtFiles(forStatus('authenticated'));

    expect(screen.getByText('PROTECTED CONTENT')).toBeInTheDocument();
    expect(screen.queryByText('LANDING PAGE')).not.toBeInTheDocument();
  });

  it('when authenticated: reads notifications with NO consumer mounted (SPEC-059 FR-005)', async () => {
    // THE DISCRIMINATING OBSERVATION, and it needs the header ABSENT to be one. `Header`
    // mounts `useNotifications(username)`, whose query key and fetch are byte-identical to
    // `prefetchNotifications`' — so with a header in the tree the read happens either way and
    // deleting ProtectedLayout's effect changes nothing observable. With no consumer mounted,
    // the prefetch is the only thing that can issue this call.
    renderAtFiles(forStatus('authenticated'));

    await waitFor(() => expect(mockGetNotifications).toHaveBeenCalledWith('alice'));
  });

  it('when authenticated: the header shows the unread count on first paint', async () => {
    // WHAT THE PREFETCH IS FOR, as the user sees it. On its own this would not prove the
    // prefetch ran (the header's own hook would fetch the same thing); paired with the test
    // above it says the warmed cache produces the right count rather than a wrong one.
    mockGetNotifications.mockResolvedValue({
      success: true,
      data: [
        {id: '2', message: 'b', read: false, timestamp: '2026-06-02T00:00:00.000Z'},
        {id: '1', message: 'a', read: true, timestamp: '2026-06-01T00:00:00.000Z'}
      ]
    });

    renderAtFiles(forStatus('authenticated'), {withHeader: true});

    expect(await screen.findByRole('link', {name: 'Notifications, 1 unread'})).toBeInTheDocument();
  });

  it('reads the feature-flag document once the shell mounts (SPEC-162 FR-009)', async () => {
    // THE HOOK'S RESULT IS DISCARDED UNTIL SPEC-163, WHICH MAKES THE CALL LOOK LIKE DEAD
    // CODE. It is not. Without a mount, Rollup drops the whole feature from the production
    // bundle — and then the `_config/*` grant, the bucket-policy allowlist, the CORS
    // preflight, the CSP `connect-src` entry, the key spelling and the credential timing are
    // all UNEXERCISED in production while every gate stays green. That is SPEC-137's shape,
    // and it is also why FR-009's live check exists: it observes this request, and it cannot
    // observe one that nothing issues.
    renderAtFiles(forStatus('authenticated'));

    await waitFor(() => expect(mockGetFeatureFlags).toHaveBeenCalled());
  });

  it('when unauthenticated: nothing is read for a signed-out user', async () => {
    renderAtFiles(forStatus('unauthenticated'));

    // The redirect happened, so there is no bell to look at — the observable outcome is that
    // no notifications request was made at all. `prefetchNotifications` returns early on a
    // null username, and a regression there would show up here as an unexpected read.
    await waitFor(() => expect(screen.getByText('LANDING PAGE')).toBeInTheDocument());
    expect(mockGetNotifications).not.toHaveBeenCalled();
    // The flags read is gated the same way — a fetch issued before there are credentials is
    // a guaranteed failure that would pin the whole session to 'fallback'.
    expect(mockGetFeatureFlags).not.toHaveBeenCalled();
  });
});
