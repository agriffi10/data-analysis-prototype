import {QueryWorkspace} from '../features/query/QueryWorkspace';
import {usePageTitle} from '../hooks/usePageTitle';

/** The query workspace page (`/query`). */
export default function QueryPage() {
  usePageTitle('Query');
  return <QueryWorkspace />;
}
