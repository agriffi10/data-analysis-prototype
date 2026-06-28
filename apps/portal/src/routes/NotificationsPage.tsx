import {NotificationsPage as NotificationsView} from '../features/notifications';

// The `/notifications` route (SPEC-060) — reached via the header bell link, not the
// primary tab bar. Chrome + auth gate live in ProtectedLayout/Header; the feature
// view owns the data hook and its own document title (with the unread count), so
// this route component is a thin default-export wrapper (route-component convention).
export default function NotificationsPage() {
  return <NotificationsView />;
}
