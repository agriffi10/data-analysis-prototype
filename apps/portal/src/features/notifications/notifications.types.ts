// Browser data-layer types for the per-user notifications inbox. These match the
// writer Lambda's wire contract exactly — the writer owns the on-S3 shape.

export type Notification = {
  /** Server-assigned by the writer Lambda. */
  id: string;
  message: string;
  read: boolean;
  /** ISO-8601, writer clock. */
  timestamp: string;
  /**
   * Optional in-app path the message links to, e.g. `/data-quality/alice/req-1`.
   * Supplied by a trusted producer on `create` and persisted
   * verbatim by the writer.
   *
   * It is NOT trusted at render: it arrives from outside the SPA and becomes a
   * clickable anchor, so `isSafeInAppPath` gates it and the row falls back to plain
   * text on anything that could leave this origin. Absent on every notification
   * written before this field existed, and on every producer that supplies none —
   * both render exactly as they always have.
   */
  link?: string;
  /**
   * Optional structured field a trusted producer attaches beside the message, for a
   * reader that knows the producing plane's shape. Persisted verbatim by the writer,
   * which bounds its SIZE and refuses anything over that — never its contents.
   *
   * Like `link`, it is absent on every notification written before the field existed and
   * on every producer that supplies none, and both render exactly as they always have.
   * Unlike `link` it is not a safety decision: it becomes no anchor and no markup. What
   * the reader owes it is a field-by-field rebuild, which is what `normalize` does.
   */
  payload?: NotificationPayload;
};

/**
 * What a payload carries. Owned by the WRITER's wire contract rather than by any one
 * feature — a notification row must never import from the feature its producer belongs to.
 *
 * `requestId` is the one field every producer's payload carries, a wholly successful run's
 * included, because a reader settles its own record of a request by matching it — so a
 * payload without one is read as no payload. Every other field this type declares belongs to
 * file operations, whose runs are asynchronous and whose result a user has to be able to act
 * on after the submitting tab is gone: it is what rebuilding that request needs. A results
 * conversion's payload also carries `format`, which nothing here reads, so the normaliser
 * drops it.
 */
export type NotificationPayload = {
  /** The run this notification is about. Always present. */
  requestId: string;
  operation?: string;
  /** The space the items came from — NOT derivable from an absolute key. */
  source?: {kind?: string; name?: string};
  /** Absent for an operation that has no destination, i.e. a delete. */
  destination?: {kind?: string; name?: string; prefix?: string};
  /**
   * The items something already occupied the destination of. BOUNDED at the producer, by
   * bytes as well as by count — one entry is a couple of hundred bytes at ordinary key
   * lengths and thousands at the plane's caps — so `more` says whether any were dropped.
   */
  conflicts?: NotificationConflict[];
  more?: boolean;
};

/** One conflicted item, carrying what a re-submit of it needs. */
export type NotificationConflict = {
  itemKey: string;
  kind?: string;
  /** The name the item was to take, which a rename has no other source for. */
  targetName?: string;
  /** A bounded sample of the colliding keys, already shortened for display. */
  sample?: string[];
  more?: boolean;
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
