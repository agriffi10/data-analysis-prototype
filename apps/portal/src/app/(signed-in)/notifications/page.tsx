'use client';
import dynamic from 'next/dynamic';

/**
 * The Notifications view, loaded in the browser only. A page's static imports run at hydration, before
 * the runtime document arrives, so the view is reached only through this client-only import, which
 * runs after the boot.
 */
const NotificationsView = dynamic(
  () => import('../../../routes/areas/notifications').then((module) => module.NotificationsView),
  {ssr: false}
);

/**
 * Notifications, served by the App Router. It takes no props: the seam carries the address, and a native
 * navigation would leave Next's props stale.
 *
 * @returns The Notifications view.
 */
export default function NotificationsPage() {
  return <NotificationsView />;
}
