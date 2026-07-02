import {ConnectionsPage as ConnectionsView} from '../features/shared-spaces';
import {usePageTitle} from '../hooks/usePageTitle';

/** The Connections tab (`/connections`) — manage shared spaces. */
export default function ConnectionsPage() {
  usePageTitle('Connections');
  return <ConnectionsView />;
}
