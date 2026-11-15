'use client';
import dynamic from 'next/dynamic';
import {usePageTitleOnMount} from '../../../hooks/usePageTitle';

const QueryView = dynamic(() => import('../../../routes/areas/query').then((m) => m.QueryView), {ssr: false});

/**
 * The Query workspace's App Router page, at `/query`.
 *
 * The view is reached only through `next/dynamic` with `ssr: false`, because a page's static imports
 * are evaluated at hydration, before the boot has loaded the runtime document the view's modules read.
 * There is no loading fallback: the view's own `Suspense` shows the loading state while the
 * workspace's chunk arrives. The page takes no props, because a native navigation leaves
 * `searchParams` as they were; the workspace reads the address through the seam. The runs it starts
 * live in the signed-in shell above every page, so leaving it ends none of them.
 *
 * @returns The Query view.
 */
export default function QueryPage() {
  usePageTitleOnMount('Query');
  return <QueryView />;
}
