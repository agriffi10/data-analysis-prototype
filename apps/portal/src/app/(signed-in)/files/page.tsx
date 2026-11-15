'use client';
import dynamic from 'next/dynamic';

/**
 * The Files view, loaded in the browser only. A page's static imports run at hydration, before
 * the runtime document arrives, so the view is reached only through this client-only import, which
 * runs after the boot.
 */
const FilesView = dynamic(() => import('../../../routes/areas/files').then((module) => module.FilesView), {ssr: false});

/**
 * Files, served by the App Router. It takes no props: the seam carries the address, and a native
 * navigation would leave Next's props stale.
 *
 * @returns The Files view.
 */
export default function FilesPage() {
  return <FilesView />;
}
