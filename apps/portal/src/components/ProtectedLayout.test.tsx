import {describe, it, expect, vi, beforeEach, afterEach, type MockedFunction} from 'vitest';
import {render, screen, cleanup} from '@testing-library/react';
import {MemoryRouter, Routes, Route} from 'react-router';
import {QueryClientProvider} from '@tanstack/react-query';
import {ProtectedLayout} from './ProtectedLayout';
import {Header} from './Header';
import {AuthContext} from '../features/auth/authContext';
import {createTestQueryClient} from '../test/renderWithProviders';
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

import {setReturnPath} from '../lib/returnPath';
import {getNotifications} from '../features/notifications/notifications.service';

const mockGetNotifications = vi.mocked(getNotifications);
const mockSetReturnPath = setReturnPath as unknown as MockedFunction<(path: string) => void>;

const forStatus = (status: AuthStatus): AuthContextValue =>
  status === 'authenticated' ? authenticated('alice') : status === 'loading' ? authLoading() : unauthenticated();

/**
 * Mirrors the App route tree: a public landing marker plus the protected /files child,
 * entered at /files so the guard decides what mounts. Bespoke by necessity — route
 * composition is the subject, so `renderWithProviders`' own router cannot be nested (FR-007).
 * The real `Header` rides along so the prefetch has somewhere observable to land.
 */
const renderAtFiles = (auth: AuthContextValue) =>
  render(
    <AuthContext.Provider value={auth}>
      <QueryClientProvider client={createTestQueryClient()}>
        <MemoryRouter initialEntries={['/files']}>
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
                    <Header />
                    <div>PROTECTED CONTENT</div>
                  </>
                }
              />
            </Route>
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>
    </AuthContext.Provider>
  );

beforeEach(() => {
  vi.clearAllMocks();
  mockGetNotifications.mockResolvedValue({success: true, data: []});
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

  it('when authenticated: the header shows the unread count without ever showing a spinner', async () => {
    // WHAT THE PREFETCH IS FOR (SPEC-059 FR-005), asserted as the user sees it. The old test
    // asserted a stub had been called with ('alice'), which a prefetch that populated nothing
    // would also satisfy. Here the real prefetch runs against the mocked service and the bell
    // is read for its accessible name — the count is the outcome, the call is the mechanism.
    mockGetNotifications.mockResolvedValue({
      success: true,
      data: [
        {id: '2', message: 'b', read: false, timestamp: '2026-06-02T00:00:00.000Z'},
        {id: '1', message: 'a', read: true, timestamp: '2026-06-01T00:00:00.000Z'}
      ]
    });

    renderAtFiles(forStatus('authenticated'));

    expect(await screen.findByRole('link', {name: 'Notifications, 1 unread'})).toBeInTheDocument();
    expect(screen.queryByRole('status')).not.toBeInTheDocument();
    expect(mockGetNotifications).toHaveBeenCalledWith('alice');
  });

  it('when unauthenticated: nothing is read for a signed-out user', () => {
    renderAtFiles(forStatus('unauthenticated'));

    // The redirect happened, so there is no bell to look at — the observable outcome is that
    // no notifications request was made at all. `prefetchNotifications` returns early on a
    // null username, and a regression there would show up here as an unexpected read.
    expect(screen.getByText('LANDING PAGE')).toBeInTheDocument();
    expect(mockGetNotifications).not.toHaveBeenCalled();
  });
});
