import {DataExplorerWorkspace} from '../features/data-explorer';
import {usePageTitle} from '../hooks/usePageTitle';

/** The Data Explorer page (`/explore`). Lazily loaded — it pulls the Athena and Glue clients. */
export default function ExplorePage() {
  usePageTitle('Data Explorer');
  return <DataExplorerWorkspace />;
}
