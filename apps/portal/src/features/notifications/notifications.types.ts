// Browser data-layer types for the per-user notifications inbox. These match the
// writer Lambda's wire contract exactly — the writer owns the on-S3 shape.

export type Notification = {
  /** Server-assigned by the writer Lambda. */
  id: string;
  message: string;
  read: boolean;
  /** ISO-8601, writer clock. */
  timestamp: string;
};

/**
 * The two browser-originated actions. `create` is trusted-producer-only and there
 * is no delete — the inbox only grows (writer-capped) and the user marks items read.
 */
export type NotificationAction = 'markRead' | 'markAllRead';

/** Input to `enqueueNotificationAction`. */
export type EnqueueNotificationInput = {
  action: NotificationAction;
  /**
   * Used ONLY as the FIFO MessageGroupId (per-user ordering) — not sent in the body
   * and not trusted by the writer, which derives the target user from the verified
   * ID token the service attaches.
   */
  username: string;
  /** Required for `markRead`. */
  id?: string;
};

/** The on-S3 document shape: an array root at {username}/user_settings/notifications.json. */
export type NotificationsStore = Notification[];
