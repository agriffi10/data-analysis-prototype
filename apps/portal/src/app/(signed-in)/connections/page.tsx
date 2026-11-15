'use client';
import dynamic from 'next/dynamic';
import {usePageTitleOnMount} from '../../../hooks/usePageTitle';

/**
 * The shared-spaces view, loaded in the browser only. A page file's static imports are evaluated at
 * hydration, before the runtime document arrives, so the view is reached through this client-only
 * dynamic import, which runs after the boot. It shows no loading state of its own: the view's own
 * `Suspense` does, once its chunk is here.
 */
const ConnectionsView = dynamic(
  () => import('../../../routes/areas/connections').then((module) => module.ConnectionsView),
  {ssr: false}
);

/**
 * Shared spaces, at `/connections`.
 *
 * @returns The shared-spaces view.
 */
export default function ConnectionsPage() {
  usePageTitleOnMount('Shared spaces');
  return <ConnectionsView />;
}
