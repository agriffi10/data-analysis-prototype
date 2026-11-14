'use client';
import dynamic from 'next/dynamic';
import type {ReactNode} from 'react';

/**
 * The boot, loaded in the browser only. `ssr: false` is what keeps every module of the application
 * graph off the server: it reads configuration and the browser's own storage, and it was written
 * for a document that already exists. Measured: a provider that reads configuration, rendered in a
 * layout on the server, builds green and then answers 500 on every page under `next start`.
 */
const PortalBoot = dynamic(() => import('../PortalBoot').then((module) => module.PortalBoot), {ssr: false});

/**
 * The client boundary the root layout renders around every page: the boot, then the frame, then
 * the page.
 *
 * @param props.children - The page Next selected.
 * @returns The client-only boot around the page.
 */
export function PortalMount({children}: {children: ReactNode}) {
  return <PortalBoot>{children}</PortalBoot>;
}
