'use client';
import dynamic from 'next/dynamic';
import {CatchAllRouter} from '../../lib/navigation';

/**
 * The route table, loaded in the browser only. A page file's static imports are evaluated at
 * hydration, before the runtime document arrives, so the application graph is reached only through
 * this client-only dynamic import, which runs after the boot.
 */
const RouteTable = dynamic(() => import('../../routes/table').then((module) => module.RouteTable), {ssr: false});

/**
 * Every page the App Router does not serve yet, matched by react-router inside the seam.
 *
 * @returns The catch-all's router around its table.
 */
export function CatchAllMount() {
  return (
    <CatchAllRouter>
      <RouteTable />
    </CatchAllRouter>
  );
}
