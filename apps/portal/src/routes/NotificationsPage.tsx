import {NotificationsPage as NotificationsView} from '../features/notifications';

/** The `/notifications` route — reached via the header bell link; the feature view owns the data and document title. */
export default function NotificationsPage() {
  return <NotificationsView />;
}
