import NotificationsPage from '../NotificationsPage';

/**
 * The notifications inbox, at `/notifications`, reached by the header bell rather than the tab bar.
 *
 * Eager: the notifications service is already in the main bundle through the header bell, so a
 * lazy page would save nothing.
 *
 * @returns The inbox.
 */
export function NotificationsView() {
  return <NotificationsPage />;
}
