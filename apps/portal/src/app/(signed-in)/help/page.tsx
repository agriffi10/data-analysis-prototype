'use client';
import dynamic from 'next/dynamic';

/**
 * The Help view, loaded in the browser only. A page's static imports run at hydration, before
 * the runtime document arrives, so the view is reached only through this client-only import, which
 * runs after the boot.
 */
const HelpView = dynamic(() => import('../../../routes/areas/help').then((module) => module.HelpView), {ssr: false});

/**
 * Help, served by the App Router. It takes no props: the seam carries the address, and a native
 * navigation would leave Next's props stale.
 *
 * @returns The Help view.
 */
export default function HelpPage() {
  return <HelpView />;
}
