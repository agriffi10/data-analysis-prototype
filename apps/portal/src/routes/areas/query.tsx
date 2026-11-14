import {Suspense, lazy} from 'react';
import {ErrorBoundary} from '../../components/ErrorBoundary';
import {LoadingState} from '../../components/LoadingState';
import {FeatureRoute} from '../FeatureRoute';

// The Query page pulls in Monaco and the catalog clients, so the whole page is lazy and none of it
// lands in the main bundle.
const QueryPage = lazy(() => import('../QueryPage'));

/**
 * The Query workspace, at `/query`.
 *
 * `FeatureRoute` sits OUTSIDE the boundaries on purpose: it decides whether the page mounts at all,
 * and a lazy chunk that loads before the answer arrives is a page that has already started fetching.
 *
 * The `Suspense` is wrapped because it has no error path: a chunk-load rejection (the accepted
 * rollover race) lands in this boundary rather than the shell's. Each lazy view's boundary carries
 * its own key for the day two routes render one view component: React would reuse one boundary
 * across them, pinning a failed chunk's fallback on the next page. While each route renders its own
 * view component, React remounts the boundary on a route change whatever its key.
 *
 * @returns The workspace behind its flag, its boundary and its loading state.
 */
export function QueryView() {
  return (
    <FeatureRoute flag="query">
      <ErrorBoundary key="query">
        <Suspense fallback={<LoadingState />}>
          <QueryPage />
        </Suspense>
      </ErrorBoundary>
    </FeatureRoute>
  );
}
