import {DataExplorerWorkspace} from '../features/data-explorer';
import {usePageTitle} from '../hooks/usePageTitle';

/**
 * The Data Explorer page (`/explore`). Lazily loaded — it pulls the Athena and Glue clients.
 *
 * The page owns the `<main id="main">` landmark, the skip link's target, so every state the
 * workspace renders — the picker, a tab, a refused link — sits inside it.
 */
export default function ExplorePage() {
  usePageTitle('Data Explorer');
  return (
    <main
      id="main"
      className="flex min-h-0 min-w-0 flex-1 flex-col">
      <DataExplorerWorkspace />
    </main>
  );
}
