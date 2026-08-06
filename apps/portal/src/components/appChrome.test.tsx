import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';
import {cleanup, fireEvent, screen} from '@testing-library/react';
import {useState} from 'react';
import {Header} from './Header';
import {AuthContext} from '../features/auth/authContext';
import {renderWithProviders} from '../test/renderWithProviders';
import {authValue, authenticated, unauthenticated} from '../test/authFixtures';
import {Route, Routes, useNavigate} from 'react-router';
import {RootLayout} from './RootLayout';
import type {AuthContextValue} from '../features/auth';

// ─── from Header.test.tsx ───
vi.mock('../features/notifications/notifications.service', () => ({
  getNotifications: vi.fn().mockResolvedValue({success: true, data: []}),
  enqueueNotificationAction: vi.fn().mockResolvedValue({success: true, data: undefined})
}));

describe('Header', () => {
  /**
   * Auth is INJECTED, not mocked (SPEC-154 FR-002). `vi.mock('../features/auth')` replaced the
   * whole barrel, so the real provider never ran and no test could click a control that calls
   * it — `signOut` was a spy on a stub of a stub. The harness's `auth` option supplies a real
   * `AuthContextValue` to the real `useAuth`, which is what `LandingPage.test.tsx` already does.
   * Only the notifications SERVICE is mocked: that is the AWS boundary.
   */

  function setWidth(w: number) {
    Object.defineProperty(window, 'innerWidth', {value: w, writable: true, configurable: true});
  }

  function renderHeader(auth: AuthContextValue = unauthenticated()) {
    return renderWithProviders(<Header />, {auth, route: '/files'});
  }

  beforeEach(() => {
    setWidth(1024);
  });

  afterEach(() => {
    cleanup();
    setWidth(1024);
  });

  describe('Header hamburger (SPEC-095 FR-002)', () => {
    it('renders the hamburger + primary nav for authenticated users', () => {
      renderHeader(authenticated('alice'));

      const hamburger = screen.getByRole('button', {name: 'Open navigation'});
      expect(hamburger).toHaveClass('tablet:hidden', 'h-11', 'w-11');
      expect(hamburger).toHaveAttribute('aria-expanded', 'false');
      // aria-controls is only set while the drawer is mounted (see mobile test).
      expect(hamburger).not.toHaveAttribute('aria-controls');
      // Primary tab strip is present but desktop-only (hidden below tablet).
      expect(screen.getByRole('navigation', {name: 'Primary'}).parentElement).toHaveClass('hidden', 'tablet:flex');
      // Brand + bell remain at all widths.
      expect(screen.getByText('Data Workspace')).toBeInTheDocument();
    });

    it('does not render the hamburger for unauthenticated users', () => {
      renderHeader();
      expect(screen.queryByRole('button', {name: 'Open navigation'})).not.toBeInTheDocument();
    });

    it('opens the nav drawer on mobile when the hamburger is clicked', () => {
      setWidth(500);
      renderHeader(authenticated('alice'));

      expect(screen.queryByRole('dialog', {name: 'Navigation'})).not.toBeInTheDocument();
      fireEvent.click(screen.getByRole('button', {name: 'Open navigation'}));
      const drawer = screen.getByRole('dialog', {name: 'Navigation'});
      expect(drawer).toBeInTheDocument();
      const hamburger = screen.getByRole('button', {name: 'Open navigation'});
      expect(hamburger).toHaveAttribute('aria-expanded', 'true');
      // Linked to the now-mounted drawer.
      expect(hamburger.getAttribute('aria-controls')).toBe(drawer.id);
    });

    it('does not mount the nav drawer at desktop widths', () => {
      setWidth(1400);
      renderHeader(authenticated('alice'));
      // Even if state were open, the drawer is JS-gated to mobile only.
      expect(screen.queryByRole('dialog', {name: 'Navigation'})).not.toBeInTheDocument();
    });
  });

  describe('Header authentication controls (SPEC-154 FR-002)', () => {
    it('signs the user out when Sign out is clicked, and the header follows', async () => {
      // Nothing in the suite had ever clicked this control: `Header.tsx` renders
      // `onClick={() => void signOut()}` and coverage was three spy-count assertions inside
      // the auth provider's own test plus a synthetic probe button. A dropped handler, a
      // renamed label or a control rendered for the wrong auth state all passed green.
      //
      // The RESULTING UI STATE is the second half, and it needs the real provider's transition
      // standing in: the fixture's `signOut` cannot flip a context it does not own, so the test
      // re-renders with the signed-out value and asserts the header stops offering the account
      // controls. Without that, "the click ran" says nothing about what the user then sees.
      const signOut = vi.fn();

      // A minimal stand-in for the real provider's transition: signing out flips the context
      // the way `AuthProvider` does. `auth: null` keeps the harness from installing its own.
      function WithAuthState() {
        const [signedIn, setSignedIn] = useState(true);
        const value = signedIn
          ? authValue({
              signOut: async () => {
                signOut();
                setSignedIn(false);
              }
            })
          : unauthenticated();
        return (
          <AuthContext.Provider value={value}>
            <Header />
          </AuthContext.Provider>
        );
      }

      const {user} = renderWithProviders(<WithAuthState />, {auth: null, route: '/files'});
      expect(screen.getByText('alice')).toBeInTheDocument();

      await user.click(screen.getByRole('button', {name: 'Sign out'}));

      expect(signOut).toHaveBeenCalledTimes(1);
      expect(screen.queryByRole('button', {name: 'Sign out'})).not.toBeInTheDocument();
      expect(screen.queryByText('alice')).not.toBeInTheDocument();
    });

    it('offers no Sign out control when signed out', () => {
      renderHeader();

      expect(screen.queryByRole('button', {name: 'Sign out'})).not.toBeInTheDocument();
    });

    it('announces an auth error as an alert', () => {
      // `role="alert"` is the whole contract here — it is how a screen reader learns the
      // sign-in failed — and no test had ever rendered this banner.
      renderHeader(authValue({status: 'unauthenticated', user: null, error: 'Your session expired.'}));

      expect(screen.getByRole('alert')).toHaveTextContent('Your session expired.');
    });

    it('shows no alert region when there is no auth error', () => {
      renderHeader(authenticated('alice'));

      expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    });
  });
});

// ─── from RootLayout.test.tsx ───

describe('RootLayout', () => {
  // The Header mounts useNotifications for the bell indicator — stub the read so
  // RootLayout tests make no S3/SQS call and stay focused on layout. This is the AWS
  // boundary and the only thing mocked here.

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
});
