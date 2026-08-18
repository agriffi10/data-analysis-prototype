import './index.css';
import {Suspense, lazy} from 'react';
import {Routes, Route} from 'react-router';
import {RootLayout} from './components/RootLayout';
import {ProtectedLayout} from './components/ProtectedLayout';
import {LoadingState} from './components/LoadingState';
import {ErrorBoundary} from './components/ErrorBoundary';
import {FeatureRoute} from './routes/FeatureRoute';
import LandingPage from './routes/LandingPage';
import FilesPage from './routes/FilesPage';
import NotificationsPage from './routes/NotificationsPage';
import HelpPage from './routes/HelpPage';
import DataQualityPage from './routes/DataQualityPage';
import DataQualityReportPage from './routes/DataQualityReportPage';
import NotFoundPage from './routes/NotFoundPage';

// The Query route pulls in Monaco + the Athena/Glue SDK clients — lazy-load the
// whole route so none of it lands in the main bundle.
const QueryPage = lazy(() => import('./routes/QueryPage'));
// The Connections route pulls in the SQS client — lazy-load it too; most
// sessions never open it.
const ConnectionsPage = lazy(() => import('./routes/ConnectionsPage'));
// The Data Explorer route pulls the Athena + Glue clients — same reasoning as
// /query, minus Monaco.
const ExplorePage = lazy(() => import('./routes/ExplorePage'));

/**
 * Route definitions. RootLayout wraps every page with the shared Header;
 * ProtectedLayout is a nested sub-layout that gates protected routes on auth
 * state.
 */
export default function App() {
  return (
    <Routes>
      <Route element={<RootLayout />}>
        <Route
          path="/"
          element={<LandingPage />}
        />
        <Route element={<ProtectedLayout />}>
          {/* Every gated route keeps its path and swaps its ELEMENT. The route
              must still match, or a disabled feature would fall through to the `*` 404 and
              tell a user with a perfectly correct link that their URL is wrong.

              `FeatureRoute` is OUTSIDE the Suspense boundaries below on purpose: it decides
              whether the page mounts at all, and a lazy chunk that loads before the answer
              arrives is a page that has already started fetching. */}
          <Route
            path="/files"
            element={
              <FeatureRoute flag="files">
                <FilesPage />
              </FeatureRoute>
            }
          />
          {/* Each lazy route's Suspense is wrapped: Suspense has NO error path, so
              a chunk-load rejection (deploy-app.yml:132-139's accepted race) would
              otherwise unmount the tree. Both lazy routes are exposed, so both are
              wrapped — a fix scoped to Monaco would miss /connections. */}
          <Route
            path="/query"
            element={
              <FeatureRoute flag="query">
                <ErrorBoundary>
                  <Suspense fallback={<LoadingState />}>
                    <QueryPage />
                  </Suspense>
                </ErrorBoundary>
              </FeatureRoute>
            }
          />
          <Route
            path="/explore"
            element={
              <FeatureRoute flag="dataExplorer">
                <ErrorBoundary>
                  <Suspense fallback={<LoadingState />}>
                    <ExplorePage />
                  </Suspense>
                </ErrorBoundary>
              </FeatureRoute>
            }
          />
          <Route
            path="/connections"
            element={
              <FeatureRoute flag="sharedWorkspaces">
                <ErrorBoundary>
                  <Suspense fallback={<LoadingState />}>
                    <ConnectionsPage />
                  </Suspense>
                </ErrorBoundary>
              </FeatureRoute>
            }
          />
          {/* Reached via the header bell link, not the primary tab bar. Eager —
              the SQS client is already in the main bundle via the header bell's
              useNotifications, so lazy-loading would save nothing. */}
          <Route
            path="/notifications"
            element={<NotificationsPage />}
          />
          {/* Reached via the header help icon, not the primary tab bar. Eager —
              content is a small static module already in the main bundle. */}
          <Route
            path="/help"
            element={<HelpPage />}
          />
          {/* The runs dashboard — a primary nav destination. Eager, same
              reasoning as the report view below. Declared BEFORE the two-segment
              report route; react-router matches on specificity, not order, but
              keeping the list route first reads in the order a user meets them. */}
          <Route
            path="/data-quality"
            element={
              <FeatureRoute flag="dataQuality">
                <DataQualityPage />
              </FeatureRoute>
            }
          />
          {/* Reached from this list or from a notification's deep link —
              the space is in the path because a requestId alone doesn't say which
              space holds the report. Eager: it reuses the S3 client the Files route
              already pulls in, so lazy-loading would save nothing. */}
          {/* The gate matters MORE here than on the list route: this page reads a report
              from S3 on mount, so a page that mounted before the flag resolved would turn a
              disabled feature into an existence oracle for someone else's report — the
              exact disclosure the route is designed to avoid. */}
          <Route
            path="/data-quality/:space/:requestId"
            element={
              <FeatureRoute flag="dataQuality">
                <DataQualityReportPage />
              </FeatureRoute>
            }
          />
        </Route>
        <Route
          path="*"
          element={<NotFoundPage />}
        />
      </Route>
    </Routes>
  );
}
