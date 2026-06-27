import {SendMessageCommand} from '@aws-sdk/client-sqs';
import {GetObjectCommand} from '@aws-sdk/client-s3';
import {getSqsClient} from '../../lib/sqsClient';
import {getS3Client} from '../../lib/s3Client';
import {getIdToken} from '../../lib/awsCredentials';
import {withCredentialRetry} from '../../lib/credentialRetry';
import type {ServiceResult} from '../../types/service.types';
import type {
  SharedConnectionEntry,
  SharedConnectionsCache,
  SharedSpaceAction,
  SharedSpaceRequest
} from './sharedSpaces.types';

// The browser's ONLY shared-space write: enqueue a request onto the FIFO control
// queue (SPEC-051/056). A constant MessageGroupId serializes ALL requests so two
// users can't create the same name concurrently (SPEC-050); the requestId is the
// dedup id so an accidental resend is collapsed. The trusted actor is derived
// server-side from the verified idToken — the body `actor` is advisory.
const MESSAGE_GROUP_ID = 'shared-space';

export type EnqueueInput = {
  action: SharedSpaceAction;
  actor: string;
  space: string;
  payload?: Record<string, unknown>;
};

// Send one shared-space request. Returns the generated requestId on success.
// Never throws — returns the ServiceResult error shape.
export async function enqueueSharedSpaceRequest(input: EnqueueInput): Promise<ServiceResult<{requestId: string}>> {
  // Read at call time (not module load) so tests can stub the env (the SPEC-040
  // lesson: a module-level import.meta.env const is read before vi.stubEnv runs).
  const queueUrl = import.meta.env.VITE_SHARED_SPACE_QUEUE_URL as string | undefined;
  if (!queueUrl) {
    return {
      success: false,
      error: {message: 'Shared connections are not configured'}
    };
  }

  const token = await getIdToken();
  if (!token.success) return token;

  const requestId = crypto.randomUUID();
  const body: SharedSpaceRequest = {
    schemaVersion: 1,
    requestId,
    action: input.action,
    actor: input.actor,
    space: input.space,
    payload: input.payload ?? {},
    idToken: token.data
  };

  return withCredentialRetry(getSqsClient, async (client) => {
    try {
      await client.send(
        new SendMessageCommand({
          QueueUrl: queueUrl,
          MessageBody: JSON.stringify(body),
          MessageGroupId: MESSAGE_GROUP_ID,
          MessageDeduplicationId: requestId
        })
      );
      return {success: true, data: {requestId}};
    } catch (err) {
      const e = err as {message?: string; name?: string};
      return {
        success: false,
        error: {
          message: e.message ?? 'Failed to submit the request',
          code: e.name
        }
      };
    }
  });
}

// SPEC-052: the per-user cache the provisioning pipeline writes to
// {username}/user_settings/shared-connections.json (SPEC-056). The browser only
// READS it (the pipeline is the sole writer); `useConnections` merges it with the
// personal database. Same protected `user_settings/` folder + read pattern as
// query history / saved queries.
const VALID_STATUS = new Set(['provisioning', 'active', 'failed', 'leaving']);
const VALID_ROLE = new Set(['owner', 'member']);

const emptyCache = (): SharedConnectionsCache => ({
  version: 1,
  connections: []
});

function cacheKey(username: string): string {
  return `${username}/user_settings/shared-connections.json`;
}

function userSpaceBucket(): string {
  return import.meta.env.VITE_S3_USER_SPACE_BUCKET as string;
}

function isNotFound(err: unknown): boolean {
  const e = err as {name?: string; $metadata?: {httpStatusCode?: number}};
  return e.name === 'NoSuchKey' || e.name === 'NotFound' || e.$metadata?.httpStatusCode === 404;
}

// Keep only well-formed entries — a corrupt/partial entry is dropped, not fatal
// (same spirit as the missing-file case: degrade to what we can trust).
function isValidEntry(e: unknown): e is SharedConnectionEntry {
  const o = e as Partial<SharedConnectionEntry> | null;
  return (
    !!o &&
    typeof o.name === 'string' &&
    o.name.length > 0 &&
    typeof o.role === 'string' &&
    VALID_ROLE.has(o.role) &&
    typeof o.status === 'string' &&
    VALID_STATUS.has(o.status)
  );
}

// Forgivingly parse the cache body: a malformed/legacy file yields the empty cache
// (personal-only), never an error.
function parseCache(body: string | undefined): SharedConnectionsCache {
  if (!body) return emptyCache();
  try {
    const parsed = JSON.parse(body) as SharedConnectionsCache;
    if (parsed?.version === 1 && Array.isArray(parsed.connections)) {
      return {version: 1, connections: parsed.connections.filter(isValidEntry)};
    }
    return emptyCache();
  } catch {
    return emptyCache();
  }
}

// Read + parse the per-user shared-connections cache. A missing/corrupt file is the
// empty state (personal-only), not an error. Never throws.
export async function readSharedConnectionsCache(username: string): Promise<ServiceResult<SharedConnectionsCache>> {
  return withCredentialRetry(getS3Client, async (client) => {
    try {
      const response = await client.send(
        new GetObjectCommand({
          Bucket: userSpaceBucket(),
          Key: cacheKey(username)
        })
      );
      const body = await response.Body?.transformToString();
      return {success: true, data: parseCache(body)};
    } catch (err) {
      if (isNotFound(err)) return {success: true, data: emptyCache()};
      const e = err as {message?: string; name?: string};
      return {
        success: false,
        error: {
          message: e.message ?? 'Failed to load shared connections',
          code: e.name
        }
      };
    }
  });
}
