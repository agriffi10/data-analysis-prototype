'use client';
import dynamic from 'next/dynamic';

/**
 * The Data Explorer's view, loaded in the browser only. A page file's static imports are evaluated
 * at hydration, before the runtime document arrives, so the view is reached through this client-only
 * dynamic import, which runs after the boot. It shows no loading state of its own: the view's own
 * `Suspense` does, once its chunk is here.
 */
const ExploreView = dynamic(() => import('../../../routes/areas/explore').then((module) => module.ExploreView), {
  ssr: false
});

/**
 * The Data Explorer, at `/explore`. It reads its search through the navigation seam, never from the
 * `searchParams` prop, which a native navigation leaves stale.
 *
 * @returns The Explorer's view.
 */
export default function ExplorePage() {
  return <ExploreView />;
}
