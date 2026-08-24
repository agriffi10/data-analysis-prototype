import {readJsonDocument} from '../../lib/s3Json';
import {ok} from '../../lib/serviceResult';
import {enqueueFifoRequest} from '../../lib/enqueueFifo';
import {userSpaceBucket, userSettingsKey} from '../../lib/userSpace';
import type {ServiceResult} from '../../types/service.types';
import type {
  EnqueueNotificationInput,
  Notification,
  NotificationConflict,
  NotificationPayload
} from './notifications.types';
import {configValue} from '../../lib/runtimeConfig';

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
    ...(normalizePayload(row.payload) ? {payload: normalizePayload(row.payload)} : {})
  };
}

// A payload is carried only when it is a plain object whose `requestId` is a string of the
// shape the producer mints — a 32-character hex UUID. Everything else is dropped, and the
// ROW SURVIVES either way: this keeps the field's type honest exactly as the `link` clause
// does, it does not police the producer.
//
// The id is shape-checked rather than merely non-empty because it does not stay data: the
// row interpolates it into a URL. Its round trip is what makes it untrusted here rather than
// its origin: the browser mints it, the file-operations plane echoes it back into a
// notification, and it arrives read out of an S3 object — so nothing between here and the
// mint is this module's to vouch for. The writer refuses a `create` sent with browser
// credentials, which closes the path by which a signed-in user could plant a chosen value in
// ANOTHER user's inbox; it does not make the field checked, and this is the only place it is.
//
// The rule is "characters that cannot change a URL", NOT "a UUID". Every plane mints
// `crypto.randomUUID()` today, and a regex for that exact shape would be a reader coupled to
// one producer's id format — which fails closed in the worst way, dropping the field silently
// the day a plane mints anything else. The render site encodes the value as well.
const ID_SHAPE = /^[A-Za-z0-9_-]{1,64}$/;

// The payload is rebuilt FIELD BY FIELD, exactly like the row around it, and for the same
// reason the row is: what arrives is untrusted data whose declared type is a promise nobody
// checked. Carrying the object through unexamined would let `conflicts` be a string, or an
// array of nulls, or objects with no `itemKey` — all of which type as `NotificationConflict[]`
// to the next reader, which renders those fields.
function normalizePayload(payload: unknown): NotificationPayload | undefined {
  if (!payload || typeof payload !== 'object' || Array.isArray(payload)) return undefined;
  const {requestId, operation, source, destination, conflicts, more} = payload as Record<string, unknown>;
  if (typeof requestId !== 'string' || !ID_SHAPE.test(requestId)) return undefined;

  const conflictRows = Array.isArray(conflicts) ? conflicts.map(normalizeConflict).filter(isPresent) : [];
  return {
    requestId,
    ...(typeof operation === 'string' ? {operation} : {}),
    ...(normalizeSpace(source) ? {source: normalizeSpace(source)} : {}),
    ...(normalizeSpace(destination) ? {destination: normalizeSpace(destination)} : {}),
    ...(conflictRows.length > 0 ? {conflicts: conflictRows} : {}),
    // True when the producer said so, and ALSO when this reader dropped a malformed entry —
    // otherwise a list silently shortened here reads as the complete one.
    ...(more === true || conflictRows.length !== (Array.isArray(conflicts) ? conflicts.length : 0) ? {more: true} : {})
  };
}

function normalizeSpace(space: unknown): {kind?: string; name?: string; prefix?: string} | undefined {
  if (!space || typeof space !== 'object' || Array.isArray(space)) return undefined;
  const {kind, name, prefix} = space as Record<string, unknown>;
  return {
    ...(typeof kind === 'string' ? {kind} : {}),
    ...(typeof name === 'string' ? {name} : {}),
    ...(typeof prefix === 'string' ? {prefix} : {})
  };
}

// `itemKey` is the one required field: it is this entry's identity, and an entry without one
// is not a shorter record, it is an unusable one.
function normalizeConflict(row: unknown): NotificationConflict | undefined {
  if (!row || typeof row !== 'object' || Array.isArray(row)) return undefined;
  const {itemKey, kind, targetName, sample, more} = row as Record<string, unknown>;
  if (typeof itemKey !== 'string' || itemKey.length === 0) return undefined;
  return {
    itemKey,
    ...(typeof kind === 'string' ? {kind} : {}),
    ...(typeof targetName === 'string' ? {targetName} : {}),
    ...(Array.isArray(sample) ? {sample: sample.filter((s): s is string => typeof s === 'string')} : {}),
    ...(more === true ? {more: true} : {})
  };
}

function isPresent<T>(value: T | undefined): value is T {
  return value !== undefined;
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
    queueUrl: configValue('notificationsQueueUrl'),
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
