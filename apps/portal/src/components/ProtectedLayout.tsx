import {type ReactNode, useEffect} from 'react';
import {Navigate, Outlet, useLocation} from 'react-router';
import {useQueryClient} from '@tanstack/react-query';
import {useAuth} from '../features/auth';
import {useExplorationEviction} from '../features/data-explorer';
import {useFeatureSet} from '../features/feature-flags';
import {UploadQueueProvider} from '../features/file-browser';
import {prefetchNotifications} from '../features/notifications';
import {setReturnPath} from '../lib/returnPath';
import {LoadingState} from './LoadingState';

// Authenticated app shell. The left rail is owned by each route's page (the file
// browser renders <Sidebar>, the query workspace renders its schema browser),
// so this is just the row container the page fills.
//
// The upload queue is mounted here (not inside the file browser) so it is
// session-scoped: in-flight uploads survive folder navigation, connection
// switches, route changes, and the file browser remounting on a `?space=`
// change. It only tears down on sign-out, when this shell unmounts.
function AppShell({children}: {children: ReactNode}) {
  return (
    <UploadQueueProvider>
      <div className="flex flex-1">{children}</div>
    </UploadQueueProvider>
  );
}

// Dev-only escape hatch: when browsing a static/public test bucket without auth
// for local work, let protected routes through. Guarded by import.meta.env.DEV
// (and the same flag the service/page use), so it is stripped from production
// builds and can never weaken the real gate.
const devBypass = import.meta.env.DEV && import.meta.env.VITE_S3_DEV_UNAUTH === 'true';

/**
 * Auth gate for protected routes. Nested inside RootLayout, so the shared
 * Header is already rendered — this sub-layout only decides whether the
 * protected page content mounts. It is a UX gate, not a security boundary;
 * IAM enforces real access via scoped credentials.
 *
 * @example
 * <Route element={<ProtectedLayout />}>
 *   <Route path="/files" element={<FilesPage />} />
 * </Route>
 */
export function ProtectedLayout() {
  const {status, user} = useAuth();
  const location = useLocation();
  const queryClient = useQueryClient();

  // Prefetch the notifications read once on authenticated app load so the
  // header indicator is accurate on first paint and the first /notifications
  // render has data. Graceful — prefetch never throws and never blocks the
  // shell from rendering.
  const username = status === 'authenticated' ? (user?.username ?? null) : null;
  useEffect(() => {
    void prefetchNotifications(queryClient, username);
  }, [queryClient, username]);

  // The Data Explorer caches an execution forever, keyed by the SQL it rendered — so a table
  // dropped and rebuilt over new data keeps answering from the old one. This watches for the
  // schema invalidation that rebuild raises and drops the affected executions. It lives in the
  // shell rather than in the Explorer because the drop usually happens in the Query workspace,
  // with the Explorer's tabs open behind it.
  useExplorationEviction();

  // The feature flags resolve here and the result is DISCARDED — the gating registry is what
  // reads them. This is not a placeholder: without a mount the whole feature is
  // tree-shaken out of the production bundle, and then the `_config/*` grant, the
  // bucket-policy allowlist, the CORS preflight, the CSP `connect-src` entry, the key
  // spelling and the credential timing are all UNEXERCISED in production while every
  // gate is green — the shape a missing layer attachment takes. The read is also what the live
  // check observes, and it cannot observe a request nothing issues.
  //
  // Session-scoped for the same reason the upload queue is: one fetch per sign-in,
  // cached for an hour, so a route change does not re-read a document that changes on a
  // deploy. It hides nothing and cannot fail the shell — an unusable document resolves
  // to the compiled-in all-on defaults.
  useFeatureSet();

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
