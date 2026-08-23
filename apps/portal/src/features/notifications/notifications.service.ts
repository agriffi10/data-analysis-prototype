import {readJsonDocument} from '../../lib/s3Json';
import {ok} from '../../lib/serviceResult';
import {enqueueFifoRequest} from '../../lib/enqueueFifo';
import {userSpaceBucket, userSettingsKey} from '../../lib/userSpace';
import type {ServiceResult} from '../../types/service.types';
import type {EnqueueNotificationInput, Notification, NotificationPayload} from './notifications.types';

// Browser data layer for the per-user notifications inbox. The browser never writes
// notifications.json — the writer Lambda is the sole writer. This service only reads
// the inbox and enqueues the two user actions (markRead/markAllRead) onto the FIFO queue.

function inboxKey(username: string): string {
  return userSettingsKey(username, 'notifications.json');
}

// A corrupt or partial row is dropped, not fatal — the writer owns the format; the
// reader is defensive.
//
// IT REQUIRES THE FOUR CORE FIELDS AND NOTHING MORE, DELIBERATELY. The document is a bare
// array with no version, so a reader that met an unknown field and refused the row would
// drop notifications the moment a producer started sending one — which is exactly what
// happened here when `link` arrived, and again when `payload` did. Tightening this into
// validating the optional fields would trade a rendering decision for a data-loss one.
function isValidRow(row: unknown): row is Notification {
  const o = row as Partial<Notification> | null;
  return (
    !!o &&
    typeof o.id === 'string' &&
    o.id.length > 0 &&
    typeof o.message === 'string' &&
    typeof o.timestamp === 'string'
  );
}

// `read` is coerced to a boolean so a legacy/missing flag never counts as unread.
//
// `link` is carried through only when it is a string, and is NOT validated here: the
// safety decision belongs at the render site (`isSafeInAppPath`), where the value
// actually becomes an anchor. Dropping a non-string keeps the field's type honest;
// this rebuild is field-by-field, so anything not named here is discarded by design.
function normalize(row: Notification): Notification {
  return {
    id: row.id,
    message: row.message,
    read: row.read === true,
    timestamp: row.timestamp,
    ...(typeof row.link === 'string' ? {link: row.link} : {}),
    ...(isPayload(row.payload) ? {payload: row.payload} : {})
  };
}

// A payload is carried only when it is a plain object whose `requestId` is a string of the
// shape the producer mints — a 32-character hex UUID. Everything else is dropped, and the
// ROW SURVIVES either way: this keeps the field's type honest exactly as the `link` clause
// does, it does not police the producer.
//
// The id is shape-checked rather than merely non-empty because it does not stay data: the
// row interpolates it into a URL. It arrives from outside the SPA, read back out of S3, on
// a queue the portal role can also write to.
//
// The rule is "characters that cannot change a URL", NOT "a UUID". Every plane mints
// `crypto.randomUUID()` today, and a regex for that exact shape would be a reader coupled to
// one producer's id format — which fails closed in the worst way, dropping the field silently
// the day a plane mints anything else. The render site encodes the value as well.
const ID_SHAPE = /^[A-Za-z0-9_-]{1,64}$/;

function isPayload(payload: unknown): payload is NotificationPayload {
  if (!payload || typeof payload !== 'object' || Array.isArray(payload)) return false;
  const {requestId} = payload as Partial<NotificationPayload>;
  return typeof requestId === 'string' && ID_SHAPE.test(requestId);
}

// Forgiving parse: missing/corrupt/non-array → empty list. Returned newest-first —
// the writer already stores newest-first; the reader re-sorts to be resilient.
function parseInbox(body: string | undefined): Notification[] {
  if (!body) return [];
  let parsed: unknown;
  try {
    parsed = JSON.parse(body);
  } catch {
    console.warn('notifications.json is not valid JSON; treating as empty');
    return [];
  }
  if (!Array.isArray(parsed)) {
    console.warn('notifications.json root is not an array; treating as empty');
    return [];
  }
  return parsed
    .filter(isValidRow)
    .map(normalize)
    .sort((a, b) => b.timestamp.localeCompare(a.timestamp));
}

/**
 * Read and parse the user's notifications inbox. A missing file (new user) is the
 * empty state, not an error; any other S3 error surfaces as a typed failure.
 */
export async function getNotifications(username: string): Promise<ServiceResult<Notification[]>> {
  return readJsonDocument({
    bucket: userSpaceBucket(),
    key: inboxKey(username),
    parse: (body) => ok(parseInbox(body)),
    onMissing: () => ({success: true, data: []}),
    fallbackMessage: 'Failed to load notifications'
  });
}

/**
 * Enqueue one user-action message onto the notifications FIFO queue.
 *
 * The writer applies the action asynchronously, so success means enqueued, not
 * applied. The body carries the caller's ID token — the writer derives the target
 * username from the verified claim (anti-spoofing), never from the body.
 * MessageGroupId = username serializes the user's actions behind any system
 * creates for them; a fresh dedup id lets each (idempotent) action through.
 */
export async function enqueueNotificationAction(input: EnqueueNotificationInput): Promise<ServiceResult<void>> {
  if (input.action === 'markRead' && !input.id) {
    // Coded, like every other failure, so `toUserMessage` maps rather than falls
    // through by accident. No rule matches `InvalidRequest` on purpose — this is a
    // caller bug the UI cannot produce, and GENERIC is the right thing to show if
    // it somehow does.
    return {success: false, error: {message: 'markRead requires a notification id', code: 'InvalidRequest'}};
  }

  return enqueueFifoRequest<void>({
    // Read at call time (not module load) so tests can stub the env — a module-level
    // import.meta.env const is read before vi.stubEnv runs.
    queueUrl: import.meta.env.VITE_NOTIFICATIONS_QUEUE_URL as string | undefined,
    notConfiguredMessage: 'Notifications are not configured',
    build: (idToken) => ({
      body: {
        action: input.action,
        idToken,
        ...(input.action === 'markRead' ? {id: input.id} : {})
      },
      messageGroupId: input.username,
      deduplicationId: crypto.randomUUID(),
      data: undefined
    })
  });
}
