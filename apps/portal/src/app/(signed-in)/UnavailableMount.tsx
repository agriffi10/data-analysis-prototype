'use client';
import dynamic from 'next/dynamic';
import type {ComponentProps} from 'react';

/** The view, reached client-only so the application graph is evaluated after the boot. */
const UnavailableView = dynamic(
  () => import('../../routes/areas/unavailable').then((module) => module.UnavailableView),
  {ssr: false}
);

/**
 * What an area's server layout renders in place of its page when the server holds a set with the
 * area's flag off: the "not available" page, reached as a page reaches its view.
 *
 * It imports nothing of the application graph, its props typed from the view through `next/dynamic`,
 * because a server layout's client import is hydrated before the boot.
 *
 * @param props.flag - The flag that is off.
 * @param props.fallback - The first enabled flag with a destination, or none.
 * @returns The unavailable view.
 */
export function UnavailableMount(props: ComponentProps<typeof UnavailableView>) {
  return <UnavailableView {...props} />;
}
