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
 * rollover race) lands in this boundary rather than the shell's. Each area is its own page, so a
 * route change mounts a new boundary and a failed chunk's fallback never outlives the page.
 *
 * @returns The workspace behind its flag, its boundary and its loading state.
 */
export function QueryView() {
  return (
    <FeatureRoute flag="query">
      <ErrorBoundary>
        <Suspense fallback={<LoadingState />}>
          <QueryPage />
        </Suspense>
      </ErrorBoundary>
    </FeatureRoute>
  );
}
