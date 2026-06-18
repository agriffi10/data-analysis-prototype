import { QueryWorkspace } from '../features/query/QueryWorkspace';
import { usePageTitle } from '../hooks/usePageTitle';

// The query workspace page (`/query`). Chrome (Header + primary tabs) and the
// auth gate live in ProtectedLayout/Header — this route component sets the title
// and renders the workspace (SPEC-035 FR-002). Default export per route-component
// convention.
export default function QueryPage() {
  usePageTitle('Query');
  return <QueryWorkspace />;
}
