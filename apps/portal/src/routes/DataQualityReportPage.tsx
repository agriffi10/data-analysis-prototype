import {useLocation} from '../lib/navigation';
import {useAuth} from '../features/auth';
import {DataQualityReportPage as DataQualityReportView} from '../features/data-quality';
import {linkFlags} from '../features/feature-flags';
import {FeatureRoute} from './FeatureRoute';

/**
 * Route wrapper — the feature view owns the page title (the Notifications convention).
 *
 * The route names its space in the PATH, so a shared space's report is gated by shared
 * workspaces as well as by `dataQuality`: with that flag off it renders the unavailable page and
 * mounts nothing that reads, rather than a report the rest of the app no longer shows. The
 * report's own "not available" banner would say the report may have been deleted, which is
 * false about a report that returns the moment the flag does.
 */
export default function DataQualityReportPage() {
  const {pathname} = useLocation();
  const {user} = useAuth();
  const view = <DataQualityReportView />;
  return linkFlags(pathname, user?.username ?? null).includes('sharedWorkspaces') ? (
    <FeatureRoute flag="sharedWorkspaces">{view}</FeatureRoute>
  ) : (
    view
  );
}
