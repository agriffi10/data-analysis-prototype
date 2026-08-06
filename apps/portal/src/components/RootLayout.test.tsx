import {describe, it, expect, vi, afterEach} from 'vitest';
import {screen, cleanup} from '@testing-library/react';
import {Routes, Route, useNavigate} from 'react-router';
import {RootLayout} from './RootLayout';
import {renderWithProviders} from '../test/renderWithProviders';
import {unauthenticated} from '../test/authFixtures';

// The Header mounts useNotifications for the bell indicator — stub the read so
// RootLayout tests make no S3/SQS call and stay focused on layout. This is the AWS
// boundary and the only thing mocked here.
vi.mock('../features/notifications/notifications.service', () => ({
  getNotifications: vi.fn().mockResolvedValue({success: true, data: []}),
  enqueueNotificationAction: vi.fn().mockResolvedValue({success: true, data: undefined})
}));

/**
 * Route composition IS the subject here, so each test supplies its own `<Routes>` — but
 * *inside* the harness's router rather than beside a hand-rolled one (SPEC-154 FR-007),
 * which is what `LandingPage.test.tsx` already does. `route` sets the entry point.
 *
 * Auth is the REAL `useAuth` reading an injected context (FR-002). The old
 * `vi.mock('../features/auth')` replaced the whole barrel, so the provider never ran.
 */
const renderAt = (route: string, routes: React.ReactElement) =>
  renderWithProviders(routes, {route, auth: unauthenticated()});

afterEach(() => {
  cleanup();
});

describe('RootLayout', () => {
  it('renders the shared header and the child route content on non-landing routes', () => {
    renderAt(
      '/files',
      <Routes>
        <Route element={<RootLayout />}>
          <Route
            path="/files"
            element={<div>CHILD CONTENT</div>}
          />
        </Route>
      </Routes>
    );

    // "Data Workspace" comes from the Header's BrandMark.
    expect(screen.getByText('Data Workspace')).toBeInTheDocument();
    expect(screen.getByText('CHILD CONTENT')).toBeInTheDocument();
  });

  it('suppresses the app header on the landing route (it has its own nav)', () => {
    renderAt(
      '/',
      <Routes>
        <Route element={<RootLayout />}>
          <Route
            path="/"
            element={<div>LANDING CONTENT</div>}
          />
        </Route>
      </Routes>
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

    function renderBoomAt(initialEntry: string) {
      return renderAt(
        initialEntry,
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
      );
    }

    it('contains a throwing page while the header survives', () => {
      const consoleError = vi.spyOn(console, 'error').mockImplementation(() => {});
      renderBoomAt('/files');

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

      const {user} = renderAt(
        '/files',
        <>
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
        </>
      );
      expect(screen.getByRole('alert')).toBeInTheDocument();

      await user.click(screen.getByRole('button', {name: 'go to help'}));

      expect(screen.getByText('HELP CONTENT')).toBeInTheDocument();
      expect(screen.queryByRole('alert')).not.toBeInTheDocument();
      consoleError.mockRestore();
    });
  });
});
