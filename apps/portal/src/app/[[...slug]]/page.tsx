import {CatchAllMount} from './CatchAllMount';

/**
 * Every path the App Router does not serve yet: the landing page, the areas still on react-router,
 * and every unknown path. The chrome around it is the root layout's.
 *
 * @returns The catch-all's client mount.
 */
export default function CatchAllPage() {
  return <CatchAllMount />;
}
