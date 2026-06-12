import { Navigate, Outlet, useLocation } from 'react-router-dom';
import { useAuth } from '../features/auth';
import { setReturnPath } from '../lib/returnPath';

// Auth gate for protected routes (FR-003). Nested inside RootLayout, so the
// shared Header is already rendered — this sub-layout only decides whether the
// protected page content mounts. It is a UX gate, not a security boundary; IAM
// enforces real access once scoped credentials land (SPEC-011).
// Dev-only escape hatch (SPEC-013): when browsing a static/public test bucket
// without auth for local work without AWS, let protected routes through. Guarded
// by import.meta.env.DEV (and the same flag the service/page use), so it is
// stripped from production builds and can never weaken the real gate.
const devBypass =
  import.meta.env.DEV && import.meta.env.VITE_S3_DEV_UNAUTH === 'true';

export function ProtectedLayout() {
  const { status } = useAuth();
  const location = useLocation();

  if (devBypass) return <Outlet />;

  // While auth resolves, render a loading indicator instead of the Outlet, so
  // the file browser never flashes and fires no S3 requests.
  if (status === 'loading') {
    return (
      <div
        role="status"
        className="flex flex-1 items-center justify-center py-24 text-gray-400"
      >
        Loading&hellip;
      </div>
    );
  }

  // Signed out: remember where they were headed, then send them to the landing
  // page. Capturing the path here also covers signing out from a protected route.
  if (status === 'unauthenticated') {
    setReturnPath(location.pathname + location.search);
    return <Navigate to="/" replace />;
  }

  return <Outlet />;
}
