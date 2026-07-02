import {GetObjectCommand} from '@aws-sdk/client-s3';
import {SendMessageCommand} from '@aws-sdk/client-sqs';
import {getS3Client} from '../../lib/s3Client';
import {getSqsClient} from '../../lib/sqsClient';
import {getIdToken} from '../../lib/awsCredentials';
import {withCredentialRetry} from '../../lib/credentialRetry';
import type {ServiceResult} from '../../types/service.types';
import type {EnqueueNotificationInput, Notification} from './notifications.types';

// Browser data layer for the per-user notifications inbox. The browser never writes
// notifications.json — the writer Lambda is the sole writer. This service only reads
// the inbox and enqueues the two user actions (markRead/markAllRead) onto the FIFO queue.

function bucket(): string {
  return import.meta.env.VITE_S3_USER_SPACE_BUCKET as string;
}

function inboxKey(username: string): string {
  return `${username}/user_settings/notifications.json`;
}

function toServiceError(err: unknown, fallback: string) {
  const e = err as {message?: string; name?: string};
  return {
    success: false as const,
    error: {message: e.message ?? fallback, code: e.name}
  };
}

function isNotFound(err: unknown): boolean {
  const e = err as {name?: string; $metadata?: {httpStatusCode?: number}};
  return e.name === 'NoSuchKey' || e.name === 'NotFound' || e.$metadata?.httpStatusCode === 404;
}

// A corrupt or partial row is dropped, not fatal — the writer owns the format; the
// reader is defensive.
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
function normalize(row: Notification): Notification {
  return {id: row.id, message: row.message, read: row.read === true, timestamp: row.timestamp};
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
  return withCredentialRetry(getS3Client, async (client) => {
    try {
      const response = await client.send(new GetObjectCommand({Bucket: bucket(), Key: inboxKey(username)}));
      const body = await response.Body?.transformToString();
      return {success: true, data: parseInbox(body)};
    } catch (err) {
      if (isNotFound(err)) return {success: true, data: []};
      return toServiceError(err, 'Failed to load notifications');
    }
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
    return {success: false, error: {message: 'markRead requires a notification id'}};
  }

  // Read at call time (not module load) so tests can stub the env — a module-level
  // import.meta.env const is read before vi.stubEnv runs.
  const queueUrl = import.meta.env.VITE_NOTIFICATIONS_QUEUE_URL as string | undefined;
  if (!queueUrl) {
    return {success: false, error: {message: 'Notifications are not configured'}};
  }

  const token = await getIdToken();
  if (!token.success) return token;

  const body = {
    action: input.action,
    idToken: token.data,
    ...(input.action === 'markRead' ? {id: input.id} : {})
  };

  return withCredentialRetry(getSqsClient, async (client) => {
    try {
      await client.send(
        new SendMessageCommand({
          QueueUrl: queueUrl,
          MessageBody: JSON.stringify(body),
          MessageGroupId: input.username,
          MessageDeduplicationId: crypto.randomUUID()
        })
      );
      return {success: true, data: undefined};
    } catch (err) {
      return toServiceError(err, 'Failed to submit the request');
    }
  });
}
