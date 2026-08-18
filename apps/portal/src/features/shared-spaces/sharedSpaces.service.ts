import {readJsonDocument} from '../../lib/s3Json';
import {ok} from '../../lib/serviceResult';
import {enqueueFifoRequest} from '../../lib/enqueueFifo';
import {userSpaceBucket, userSettingsKey} from '../../lib/userSpace';
import type {ServiceResult} from '../../types/service.types';
import type {
  Member,
  SharedConnectionEntry,
  SharedConnectionsCache,
  SharedSpaceAction,
  SharedSpaceRequest
} from './sharedSpaces.types';

// A constant MessageGroupId serializes ALL shared-space requests so two users can't
// create the same name concurrently; the requestId doubles as the dedup id so an
// accidental resend is collapsed.
const MESSAGE_GROUP_ID = 'shared-space';

export type EnqueueInput = {
  action: SharedSpaceAction;
  actor: string;
  space: string;
  payload?: Record<string, unknown>;
};

/**
 * Enqueue one shared-space request onto the FIFO control queue — the browser's only
 * shared-space write. Returns the generated requestId on success. The trusted actor
 * is derived server-side from the verified idToken; the body `actor` is advisory.
 */
export async function enqueueSharedSpaceRequest(input: EnqueueInput): Promise<ServiceResult<{requestId: string}>> {
  const requestId = crypto.randomUUID();
  return enqueueFifoRequest({
    // Read at call time (not module load) so tests can stub the env — a module-level
    // import.meta.env const is read before vi.stubEnv runs.
    queueUrl: import.meta.env.VITE_SHARED_SPACE_QUEUE_URL as string | undefined,
    notConfiguredMessage: 'Shared connections are not configured',
    build: (idToken) => ({
      body: {
        schemaVersion: 1,
        requestId,
        action: input.action,
        actor: input.actor,
        space: input.space,
        payload: input.payload ?? {},
        idToken
      } satisfies SharedSpaceRequest,
      messageGroupId: MESSAGE_GROUP_ID,
      deduplicationId: requestId,
      data: {requestId}
    })
  });
}

// The per-user cache lives at {username}/user_settings/shared-connections.json.
// The provisioning pipeline is the sole writer; the browser only reads it.
const VALID_STATUS = new Set(['provisioning', 'active', 'failed', 'leaving', 'deleting']);
const VALID_ROLE = new Set(['owner', 'member']);

const emptyCache = (): SharedConnectionsCache => ({
  version: 1,
  connections: []
});

function cacheKey(username: string): string {
  return userSettingsKey(username, 'shared-connections.json');
}

// A corrupt/partial entry is dropped, not fatal — degrade to what we can trust.
function isValidEntry(e: unknown): boolean {
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

// Normalize one raw projection member to `Member`. A bare string is a
// legacy member and reads as `active` (FR-005); a well-formed object is passed
// through (status other than 'pending' defaults to 'active'). Malformed → null (dropped).
function normalizeMember(raw: unknown): Member | null {
  if (typeof raw === 'string') {
    return raw.length > 0 ? {username: raw, status: 'active'} : null;
  }
  const o = raw as {username?: unknown; status?: unknown} | null;
  if (!o || typeof o.username !== 'string' || o.username.length === 0) return null;
  return {username: o.username, status: o.status === 'pending' ? 'pending' : 'active'};
}

// Coerce a validated raw entry into a `SharedConnectionEntry`, normalizing the
// owner-readable `members` projection (legacy `string[]` or new `Member[]`) to `Member[]`.
function normalizeEntry(e: unknown): SharedConnectionEntry {
  const o = e as SharedConnectionEntry & {members?: unknown};
  if (o.members === undefined) return o;
  // A malformed (non-array) members field degrades to "unavailable" rather than
  // reaching the UI as a non-Member[] that a later .filter/.length would crash on.
  if (!Array.isArray(o.members)) return {...o, members: undefined};
  const members = o.members.map(normalizeMember).filter((m): m is Member => m !== null);
  return {...o, members};
}

// Forgiving parse: a malformed/legacy file yields the empty cache, never an error.
function parseCache(body: string | undefined): SharedConnectionsCache {
  if (!body) return emptyCache();
  try {
    const parsed = JSON.parse(body) as SharedConnectionsCache;
    if (parsed?.version === 1 && Array.isArray(parsed.connections)) {
      return {version: 1, connections: parsed.connections.filter(isValidEntry).map(normalizeEntry)};
    }
    return emptyCache();
  } catch {
    return emptyCache();
  }
}

/**
 * Read and parse the per-user shared-connections cache. A missing/corrupt file is
 * the empty state (personal-only), not an error.
 */
export async function readSharedConnectionsCache(username: string): Promise<ServiceResult<SharedConnectionsCache>> {
  return readJsonDocument({
    bucket: userSpaceBucket(),
    key: cacheKey(username),
    parse: (body) => ok(parseCache(body)),
    onMissing: () => ({success: true, data: emptyCache()}),
    fallbackMessage: 'Failed to load shared connections'
  });
}
