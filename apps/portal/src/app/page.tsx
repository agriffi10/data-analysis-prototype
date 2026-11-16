'use client';
import dynamic from 'next/dynamic';
import {usePageTitleOnMount} from '../hooks/usePageTitle';

/**
 * The landing page, loaded in the browser only. A page's static imports run at hydration, before
 * the runtime document arrives, so the page is reached only through this client-only import, which
 * runs after the boot.
 */
const LandingPage = dynamic(() => import('../routes/LandingPage'), {ssr: false});

/**
 * The landing page at `/`, outside the sign-in gate and without the shell, which the chrome decides
 * by path. It takes no props: the seam carries the address. Titled by the product's name alone as it
 * mounts, as the landing page titles itself.
 *
 * @returns The landing page.
 */
export default function Page() {
  usePageTitleOnMount('');
  return <LandingPage />;
}
