import {DataExplorerWorkspace} from '../features/data-explorer';
import {usePageTitle} from '../hooks/usePageTitle';

/**
 * The Data Explorer page (`/explore`). Lazily loaded — it pulls the Athena and Glue clients.
 *
 * The page owns the `<main id="main">` landmark, the skip link's target, so every state the
 * workspace renders — the picker, a tab, a refused link — sits inside it. The landmark carries
 * the workspace's viewport cap too: it is the flex item in the shell's row, and inside a column
 * the workspace's own `flex-1` decides its height and its height cap is ignored, so without the
 * cap here the page scrolls instead of the grid from tablet up.
 */
export default function ExplorePage() {
  usePageTitle('Data Explorer');
  return (
    <main
      id="main"
      className="flex min-h-0 min-w-0 flex-1 flex-col tablet:h-[calc(100dvh-3.5rem)] tablet:overflow-hidden">
      <DataExplorerWorkspace />
    </main>
  );
}
