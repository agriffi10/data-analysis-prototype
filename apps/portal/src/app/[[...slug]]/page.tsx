import {PortalMount} from './PortalMount';

/**
 * Every path the App Router does not own: the whole existing app, mounted client-only.
 *
 * @returns The client mount.
 */
export default function CatchAllPage() {
  return <PortalMount />;
}
