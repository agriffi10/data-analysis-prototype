import {Outlet, useLocation} from 'react-router-dom';
import {Header} from './Header';

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
    <div className="flex min-h-screen flex-col bg-bg">
      {/* Bypass Blocks (WCAG 2.4.1): first focusable element jumps keyboard
          users past the repeated header/nav to the page's <main id="main">. */}
      <a
        href="#main"
        className="skip-link rounded-md bg-accent px-4 py-2 text-base font-medium text-white">
        Skip to main content
      </a>
      {!isLanding && <Header />}
      <div className="flex flex-1 flex-col">
        <Outlet />
      </div>
    </div>
  );
}
