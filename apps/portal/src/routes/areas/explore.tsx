import {Suspense, lazy} from 'react';
import {ErrorBoundary} from '../../components/ErrorBoundary';
import {LoadingState} from '../../components/LoadingState';
import {FeatureRoute} from '../FeatureRoute';

// The Data Explorer pulls the catalog clients, as Query does without Monaco, so it is lazy too.
const ExplorePage = lazy(() => import('../ExplorePage'));

/**
 * The Data Explorer, at `/explore`: the flag, then a boundary, then the loading state, for the
 * reasons `QueryView` gives.
 *
 * @returns The Explorer behind its flag, its boundary and its loading state.
 */
export function ExploreView() {
  return (
    <FeatureRoute flag="dataExplorer">
      <ErrorBoundary>
        <Suspense fallback={<LoadingState />}>
          <ExplorePage />
        </Suspense>
      </ErrorBoundary>
    </FeatureRoute>
  );
}
