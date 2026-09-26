import {readJsonDocument} from '../../lib/s3Json';
import {ok} from '../../lib/serviceResult';
import {apiRequest} from '../../lib/apiClient';
import {userSpaceBucket, userSettingsKey} from '../../lib/userSpace';
import type {ServiceResult} from '../../types/service.types';
import type {
  FailedAction,
  Member,
  SharedConnectionEntry,
  SharedConnectionsCache,
  SharedSpaceAction
} from './sharedSpaces.types';

export type EnqueueInput = {
  action: SharedSpaceAction;
  actor: string;
  space: string;
  payload?: Record<string, unknown>;
};

/**
 * Enqueue one shared-space request — the browser's only shared-space write. Returns the
 * generated requestId on success.
 *
 * The actor is no longer sent: the API stamps it from the verified bearer, and a body that
 * tried to supply one is refused at the door. `EnqueueInput.actor` survives on the caller's
 * side because every call site already has the username to hand and removing it would touch
 * six components for no gain.
 */
export async function enqueueSharedSpaceRequest(input: EnqueueInput): Promise<ServiceResult<{requestId: string}>> {
  const requestId = crypto.randomUUID();
  const result = await apiRequest('sharedSpace.enqueue', {
    body: {requestId, action: input.action, space: input.space, payload: input.payload ?? {}}
  });
  return result.success ? {success: true, data: {requestId}} : result;
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
// legacy member and reads as `active`; a well-formed object is passed
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
const VALID_FAILED_ACTION = new Set<FailedAction>(['create', 'delete']);

// An unrecognized `failedAction` reads as 'create', which is what every entry written before
// the field existed was — a delete could not fail and leave a space standing. Dropping the
// field instead would be the same answer by a longer route; validating it here is what keeps
// an unchecked union member out of the row, where it would decide which verb Retry enqueues.
function normalizeFailedAction(raw: unknown): FailedAction {
  return VALID_FAILED_ACTION.has(raw as FailedAction) ? (raw as FailedAction) : 'create';
}

function normalizeEntry(e: unknown): SharedConnectionEntry {
  const o = e as SharedConnectionEntry & {members?: unknown};
  const withAction = o.failedAction === undefined ? o : {...o, failedAction: normalizeFailedAction(o.failedAction)};
  if (withAction.members === undefined) return withAction;
  const o2 = withAction as SharedConnectionEntry & {members?: unknown};
  return normalizeMembers(o2);
}

function normalizeMembers(o: SharedConnectionEntry & {members?: unknown}): SharedConnectionEntry {
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
    fallbackMessage: 'Failed to load shared spaces'
  });
}
