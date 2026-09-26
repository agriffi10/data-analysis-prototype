import {ConnectionsPage as ConnectionsView} from '../features/shared-spaces';
import {usePageTitle} from '../hooks/usePageTitle';

/** The Shared spaces tab (`/connections`) — manage shared spaces. The path kept its old name. */
export default function ConnectionsPage() {
  usePageTitle('Shared spaces');
  return <ConnectionsView />;
}
