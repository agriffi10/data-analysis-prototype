import './index.css';
import {Suspense, lazy} from 'react';
import {Routes, Route} from 'react-router-dom';
import {RootLayout} from './components/RootLayout';
import {ProtectedLayout} from './components/ProtectedLayout';
import {LoadingState} from './components/LoadingState';
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
          <Route
            path="/files"
            element={<FilesPage />}
          />
          <Route
            path="/query"
            element={
              <Suspense fallback={<LoadingState />}>
                <QueryPage />
              </Suspense>
            }
          />
          <Route
            path="/connections"
            element={
              <Suspense fallback={<LoadingState />}>
                <ConnectionsPage />
              </Suspense>
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
          {/* The runs dashboard (SPEC-123) — a primary nav destination. Eager, same
              reasoning as the report view below. Declared BEFORE the two-segment
              report route; react-router matches on specificity, not order, but
              keeping the list route first reads in the order a user meets them. */}
          <Route
            path="/data-quality"
            element={<DataQualityPage />}
          />
          {/* Reached from this list or from a notification's deep link (SPEC-114) —
              the space is in the path because a requestId alone doesn't say which
              space holds the report. Eager: it reuses the S3 client the Files route
              already pulls in, so lazy-loading would save nothing. */}
          <Route
            path="/data-quality/:space/:requestId"
            element={<DataQualityReportPage />}
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
