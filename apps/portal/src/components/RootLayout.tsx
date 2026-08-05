import {Outlet, useLocation} from 'react-router';
import {Header} from './Header';
import {NavRailProvider} from './NavRailProvider';
import {ErrorBoundary} from './ErrorBoundary';

/**
 * Layout shared by every page: the persistent auth-aware Header plus the
 * routed page content. The auth gate is a nested sub-layout (ProtectedLayout),
 * so the Header renders on public and protected routes alike. Exception: the
 * landing route ('/') renders its own self-contained nav, so the app Header is
 * suppressed there and the Outlet fills the full viewport.
 *
 * @example
 * <Route element={<RootLayout />}>
 *   <Route path="/" element={<LandingPage />} />
 * </Route>
 */
export function RootLayout() {
  const {pathname} = useLocation();
  const isLanding = pathname === '/';

  return (
    <NavRailProvider>
      <div className="flex min-h-screen flex-col bg-bg">
        {/* Bypass Blocks (WCAG 2.4.1): first focusable element jumps keyboard
            users past the repeated header/nav to the page's <main id="main">. */}
        <a
          href="#main"
          className="skip-link rounded-md bg-accent px-4 py-2 text-base font-medium text-white">
          Skip to main content
        </a>
        {!isLanding && <Header />}
        {/* Scoped BELOW the Header on purpose: a page that throws leaves the user
            with working navigation to somewhere else, rather than a bare panel.
            `key={pathname}` is what makes that true. This is a LAYOUT route, so the
            boundary instance outlives child-route changes — without the key, one
            throwing page would keep showing the fallback after the user navigated
            away, leaving the nav visible but inert. Remounting per path resets it.
            The two route-level boundaries in App.tsx need no key: they live in a
            route `element` and unmount on navigation already. */}
        <div className="flex flex-1 flex-col">
          <ErrorBoundary key={pathname}>
            <Outlet />
          </ErrorBoundary>
        </div>
      </div>
    </NavRailProvider>
  );
}
