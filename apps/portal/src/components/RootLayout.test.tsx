import {describe, it, expect, vi, beforeEach, afterEach, type MockedFunction} from 'vitest';
import {render, screen, cleanup} from '@testing-library/react';
import {MemoryRouter, Routes, Route, useNavigate} from 'react-router';
import userEvent from '@testing-library/user-event';
import {QueryClient, QueryClientProvider} from '@tanstack/react-query';
import type {ReactNode} from 'react';
import {RootLayout} from './RootLayout';
import type {AuthContextValue} from '../features/auth';

vi.mock('../features/auth', () => ({useAuth: vi.fn()}));
// The Header mounts useNotifications for the bell indicator — stub the read so
// RootLayout tests make no S3/SQS call and stay focused on layout.
vi.mock('../features/notifications/notifications.service', () => ({
  getNotifications: vi.fn().mockResolvedValue({success: true, data: []}),
  enqueueNotificationAction: vi.fn().mockResolvedValue({success: true, data: undefined})
}));

import {useAuth} from '../features/auth';

const mockUseAuth = useAuth as unknown as MockedFunction<() => AuthContextValue>;

// Header reads useNotifications (TanStack), which needs a QueryClientProvider.
const withProviders = (ui: ReactNode) => (
  <QueryClientProvider client={new QueryClient({defaultOptions: {queries: {retry: false}}})}>{ui}</QueryClientProvider>
);

beforeEach(() => {
  mockUseAuth.mockReturnValue({
    status: 'unauthenticated',
    user: null,
    error: null,
    signIn: vi.fn(),
    signUp: vi.fn(),
    signOut: vi.fn()
  });
});

afterEach(() => {
  cleanup();
});

describe('RootLayout', () => {
  it('renders the shared header and the child route content on non-landing routes', () => {
    render(
      withProviders(
        <MemoryRouter initialEntries={['/files']}>
          <Routes>
            <Route element={<RootLayout />}>
              <Route
                path="/files"
                element={<div>CHILD CONTENT</div>}
              />
            </Route>
          </Routes>
        </MemoryRouter>
      )
    );

    // "Data Workspace" comes from the Header's BrandMark.
    expect(screen.getByText('Data Workspace')).toBeInTheDocument();
    expect(screen.getByText('CHILD CONTENT')).toBeInTheDocument();
  });

  it('suppresses the app header on the landing route (it has its own nav)', () => {
    render(
      withProviders(
        <MemoryRouter initialEntries={['/']}>
          <Routes>
            <Route element={<RootLayout />}>
              <Route
                path="/"
                element={<div>LANDING CONTENT</div>}
              />
            </Route>
          </Routes>
        </MemoryRouter>
      )
    );

    // The stub landing route renders no brand mark, so the only source of
    // "Data Workspace" (the Header) must be absent.
    expect(screen.queryByText('Data Workspace')).not.toBeInTheDocument();
    expect(screen.getByText('LANDING CONTENT')).toBeInTheDocument();
  });

  // SPEC-150 FR-008. The boundary is scoped below the Header so a throwing page
  // leaves working navigation — but RootLayout is a LAYOUT route, so the boundary
  // instance outlives child-route changes. Without `key={pathname}` the fallback
  // would persist after navigating away: nav visible, content region stuck, and the
  // only escape a reload. That is the failure this pins.
  describe('the error boundary around the Outlet', () => {
    function Boom(): never {
      throw new Error('render failed');
    }

    function renderAt(initialEntry: string) {
      return render(
        withProviders(
          <MemoryRouter initialEntries={[initialEntry]}>
            <Routes>
              <Route element={<RootLayout />}>
                <Route
                  path="/files"
                  element={<Boom />}
                />
                <Route
                  path="/help"
                  element={<div>HELP CONTENT</div>}
                />
              </Route>
            </Routes>
          </MemoryRouter>
        )
      );
    }

    it('contains a throwing page while the header survives', () => {
      const consoleError = vi.spyOn(console, 'error').mockImplementation(() => {});
      renderAt('/files');

      expect(screen.getByRole('alert')).toBeInTheDocument();
      expect(screen.getByText('Data Workspace')).toBeInTheDocument();
      consoleError.mockRestore();
    });

    it('recovers on the next route, rather than pinning the fallback until a reload', async () => {
      const consoleError = vi.spyOn(console, 'error').mockImplementation(() => {});
      // A real in-router navigation. Rendering a second MemoryRouter would NOT do:
      // `initialEntries` applies at mount only, so a rerender leaves the route where
      // it was and the test would pass against the very bug it exists to catch.
      function GoHelp() {
        const navigate = useNavigate();
        return <button onClick={() => navigate('/help')}>go to help</button>;
      }

      const user = userEvent.setup();
      render(
        withProviders(
          <MemoryRouter initialEntries={['/files']}>
            {/* Outside the layout, so it survives the throw the way real nav does. */}
            <GoHelp />
            <Routes>
              <Route element={<RootLayout />}>
                <Route
                  path="/files"
                  element={<Boom />}
                />
                <Route
                  path="/help"
                  element={<div>HELP CONTENT</div>}
                />
              </Route>
            </Routes>
          </MemoryRouter>
        )
      );
      expect(screen.getByRole('alert')).toBeInTheDocument();

      await user.click(screen.getByRole('button', {name: 'go to help'}));

      expect(screen.getByText('HELP CONTENT')).toBeInTheDocument();
      expect(screen.queryByRole('alert')).not.toBeInTheDocument();
      consoleError.mockRestore();
    });
  });
});
