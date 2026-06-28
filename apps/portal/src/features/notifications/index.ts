// Notifications feature data layer (SPEC-059). UI = SPEC-060.
export {getNotifications, enqueueNotificationAction} from './notifications.service';
export {useNotifications, prefetchNotifications} from './useNotifications';
export type {UseNotificationsResult, UseNotificationsOptions} from './useNotifications';
export {notificationsKeys} from './notificationsKeys';
export type {
  Notification,
  NotificationAction,
  EnqueueNotificationInput,
  NotificationsStore
} from './notifications.types';
