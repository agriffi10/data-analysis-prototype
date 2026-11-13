'use client';
import dynamic from 'next/dynamic';

/**
 * The boot, loaded in the browser only. `ssr: false` is what keeps every module of the application
 * graph off the server: it reads configuration and the browser's own storage, and it was written
 * for a document that already exists.
 */
const PortalBoot = dynamic(() => import('../../PortalBoot').then((module) => module.PortalBoot), {ssr: false});

/**
 * The client boundary the catch-all page renders.
 *
 * @returns The client-only boot.
 */
export function PortalMount() {
  return <PortalBoot />;
}
