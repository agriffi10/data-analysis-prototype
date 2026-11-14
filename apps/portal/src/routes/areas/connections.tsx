import {Suspense, lazy} from 'react';
import {ErrorBoundary} from '../../components/ErrorBoundary';
import {LoadingState} from '../../components/LoadingState';
import {FeatureRoute} from '../FeatureRoute';

// Most sessions never open the shared-spaces page, so it is lazy.
const ConnectionsPage = lazy(() => import('../ConnectionsPage'));

/**
 * Shared spaces, at `/connections`: the flag, then a keyed boundary, then the loading state, for the
 * reasons `QueryView` gives.
 *
 * @returns The shared-spaces page behind its flag, its boundary and its loading state.
 */
export function ConnectionsView() {
  return (
    <FeatureRoute flag="sharedWorkspaces">
      <ErrorBoundary key="connections">
        <Suspense fallback={<LoadingState />}>
          <ConnectionsPage />
        </Suspense>
      </ErrorBoundary>
    </FeatureRoute>
  );
}
