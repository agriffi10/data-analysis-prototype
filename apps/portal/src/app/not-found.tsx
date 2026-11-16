'use client';
import dynamic from 'next/dynamic';
import {usePageTitleOnMount} from '../hooks/usePageTitle';

/**
 * The not-found page, loaded in the browser only. Next pulls a root `not-found.tsx` into every
 * route's hydration chunks, so a static import of the page here would put it in every route's.
 */
const NotFoundPage = dynamic(() => import('../routes/NotFoundPage'), {ssr: false});

/**
 * What Next renders, with status 404, for an address no page serves. Next reaches it only by a
 * document load, a client navigation to such an address included, so it titles itself as it mounts
 * rather than leaving the root layout's title up until its view's chunk arrives. The chrome treats a
 * path no area record claims as public, so it renders outside the gate and without the shell.
 *
 * @returns The not-found page.
 */
export default function NotFound() {
  usePageTitleOnMount('Not Found');
  return <NotFoundPage />;
}
