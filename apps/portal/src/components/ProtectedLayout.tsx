import {type ReactNode} from 'react';
import {Navigate, Outlet, useLocation} from 'react-router-dom';
import {useAuth} from '../features/auth';
import {setReturnPath} from '../lib/returnPath';
import {LoadingState} from './LoadingState';

// Authenticated app shell. The left rail is owned by each route's page (the file
// browser renders <Sidebar>, the query workspace renders its schema browser —
// which needs the editor wiring, so it can't live in the shell), so this is just
// the row container the page fills (SPEC-035 FR-002).
function AppShell({children}: {children: ReactNode}) {
  return <div className="flex flex-1">{children}</div>;
}

// Auth gate for protected routes (FR-003). Nested inside RootLayout, so the
// shared Header is already rendered — this sub-layout only decides whether the
// protected page content mounts. It is a UX gate, not a security boundary; IAM
// enforces real access once scoped credentials land (SPEC-011).
// Dev-only escape hatch (SPEC-013): when browsing a static/public test bucket
// without auth for local work without AWS, let protected routes through. Guarded
// by import.meta.env.DEV (and the same flag the service/page use), so it is
// stripped from production builds and can never weaken the real gate.
const devBypass = import.meta.env.DEV && import.meta.env.VITE_S3_DEV_UNAUTH === 'true';

export function ProtectedLayout() {
  const {status} = useAuth();
  const location = useLocation();

  if (devBypass)
    return (
      <AppShell>
        <Outlet />
      </AppShell>
    );

  // While auth resolves, render a loading indicator instead of the Outlet, so
  // the file browser never flashes and fires no S3 requests.
  if (status === 'loading') {
    return <LoadingState />;
  }

  // Signed out: remember where they were headed, then send them to the landing
  // page. Capturing the path here also covers signing out from a protected route.
  if (status === 'unauthenticated') {
    setReturnPath(location.pathname + location.search);
    return (
      <Navigate
        to="/"
        replace
      />
    );
  }

  return (
    <AppShell>
      <Outlet />
    </AppShell>
  );
}
