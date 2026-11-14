import type {ReactNode} from 'react';
import {useLocation} from '../lib/navigation';
import {Header} from './Header';
import {NavRailProvider} from './NavRailProvider';
import {ErrorBoundary} from './ErrorBoundary';

/**
 * Layout shared by every page: the persistent auth-aware Header plus the page.
 * The auth gate (ProtectedLayout) sits inside it for a signed-in page, so the
 * Header renders on public and signed-in pages alike. Exception: the landing
 * page ('/') renders its own self-contained nav, so the app Header is suppressed
 * there and the page fills the full viewport.
 *
 * @param props.children - The page, or the gate around a signed-in one.
 * @returns The layout.
 *
 * @example
 * <RootLayout><LandingPage /></RootLayout>
 */
export function RootLayout({children}: {children: ReactNode}) {
  const location = useLocation();
  const isLanding = location.pathname === '/';

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
            This layout lives in the root layout, so the boundary instance outlives every
            page change — without a reset, one throwing page would keep showing the
            fallback after the user navigated away, leaving the nav visible but inert.

            `resetKey`, NEVER a React `key`. A key remounts everything beneath it on
            every navigation, and beneath it is the signed-in shell: the upload queue
            and the in-flight file operations would be torn down by a click on a nav
            tab, aborting the uploads. The reset clears the fallback and leaves the
            shell mounted. A signed-in page's own throw is caught inside the shell, by
            ProtectedLayout's boundary; this one is for the public routes and for the
            shell itself. */}
        <div className="flex flex-1 flex-col">
          <ErrorBoundary resetKey={location.pathname + location.search}>
            {children}
          </ErrorBoundary>
        </div>
      </div>
    </NavRailProvider>
  );
}
