import type {ComponentType} from 'react';
import {Route, Routes} from 'react-router';
import {useAreaRecords, type AreaName} from '../lib/navigation';
import LandingPage from './LandingPage';
import NotFoundPage from './NotFoundPage';
import {FilesView} from './areas/files';
import {NotificationsView} from './areas/notifications';
import {HelpView} from './areas/help';
import {QueryView} from './areas/query';
import {ExploreView} from './areas/explore';
import {ConnectionsView} from './areas/connections';
import {DataQualityReportView, DataQualityView} from './areas/data-quality';

/** Each area's view for each path it serves, keyed as the area records spell them. */
const VIEWS: Record<AreaName, Record<string, ComponentType>> = {
  files: {'/files': FilesView},
  notifications: {'/notifications': NotificationsView},
  help: {'/help': HelpView},
  query: {'/query': QueryView},
  explore: {'/explore': ExploreView},
  connections: {'/connections': ConnectionsView},
  'data-quality': {'/data-quality': DataQualityView, '/data-quality/:space/:requestId': DataQualityReportView}
};

/**
 * The catch-all's route table: the landing page, every path of every area the catch-all still
 * serves, and the 404.
 *
 * Which areas it builds is read from the area records, never written here, so an area move adds its
 * App Router pages and flips its own record without editing this file: the table then stops
 * building that area's routes. Matching is case-sensitive, as Next routes. The layouts are not here:
 * the root layout holds the chrome, the gate and the shell above every page, whichever router
 * renders it.
 *
 * @returns The routes.
 */
export function RouteTable() {
  const records = useAreaRecords();
  return (
    <Routes>
      <Route
        caseSensitive
        path="/"
        element={<LandingPage />}
      />
      {records
        .filter((record) => record.router === 'catch-all')
        .flatMap((record) =>
          record.paths.map((pattern) => {
            const View = VIEWS[record.area][pattern];
            if (!View) throw new Error(`no view for ${pattern} in the ${record.area} area`);
            return (
              <Route
                key={pattern}
                caseSensitive
                path={pattern}
                element={<View />}
              />
            );
          })
        )}
      <Route
        path="*"
        element={<NotFoundPage />}
      />
    </Routes>
  );
}
