// SPEC-059: the browser data-layer types for the per-user notifications inbox.
// These match the SPEC-058 wire contract exactly (the writer Lambda owns the
// on-S3 shape) and are shared with the SPEC-060 UI.

export type Notification = {
  id: string; // server-assigned by the SPEC-058 writer
  message: string;
  read: boolean;
  timestamp: string; // ISO-8601 (writer clock)
};

// The two browser-originated actions. `create` is trusted-producer-only (SPEC-058
// FR-005; first producer = the shared-workspace control plane, SPEC-061) and there
// is NO delete — the inbox only grows (writer-capped) and the user marks items read.
export type NotificationAction = 'markRead' | 'markAllRead';

// Input to `enqueueNotificationAction`. `username` is used ONLY to set the FIFO
// `MessageGroupId` (per-user ordering, SPEC-058 FR-001) — it is NOT sent in the
// message body and is NOT trusted by the writer, which derives the target user from
// the verified ID token the service attaches. `id` is required for `markRead`.
export type EnqueueNotificationInput = {
  action: NotificationAction;
  username: string;
  id?: string;
};

// The on-S3 document shape: an array root at {username}/user_settings/notifications.json.
export type NotificationsStore = Notification[];
