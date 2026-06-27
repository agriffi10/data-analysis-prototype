import {ConnectionsPage as ConnectionsView} from '../features/shared-spaces';
import {usePageTitle} from '../hooks/usePageTitle';

// The Connections tab (`/connections`) — SPEC-052 manages shared spaces here.
// Chrome (Header + primary tabs) and the auth gate live in
// ProtectedLayout/Header; this route component sets the title and renders the
// feature view (default export per route-component convention).
export default function ConnectionsPage() {
  usePageTitle('Connections');
  return <ConnectionsView />;
}
