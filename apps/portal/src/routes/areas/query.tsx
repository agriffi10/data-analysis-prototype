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
 * rollover race) would otherwise unmount the tree. Every lazy view is wrapped, and each boundary
 * carries its OWN key: react-router renders a sibling route's element into the same slot, and the
 * lazy views have the same shape down to the page, so without distinct keys React would reuse one
 * boundary across them, pinning a failed chunk's fallback on the next page and skipping the next
 * page's loading state.
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
