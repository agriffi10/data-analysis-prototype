'use client';
import dynamic from 'next/dynamic';
import {usePageTitleOnMount} from '../../hooks/usePageTitle';
import {CatchAllRouter, useAreaRecords, useLocation} from '../../lib/navigation';
import {catchAllPageName} from './catchAllPageName';

/**
 * The route table, loaded in the browser only. A page file's static imports are evaluated at
 * hydration, before the runtime document arrives, so the application graph is reached only through
 * this client-only dynamic import, which runs after the boot.
 */
const RouteTable = dynamic(() => import('../../routes/table').then((module) => module.RouteTable), {ssr: false});

/**
 * Every page the App Router does not serve yet, matched by react-router inside the seam. It titles
 * the page as it mounts, before the table's chunk arrives, so Next's route announcer reads it.
 *
 * @returns The catch-all's router around its table.
 */
export function CatchAllMount() {
  const {pathname} = useLocation();
  usePageTitleOnMount(catchAllPageName(pathname, useAreaRecords()));
  return (
    <CatchAllRouter>
      <RouteTable />
    </CatchAllRouter>
  );
}
