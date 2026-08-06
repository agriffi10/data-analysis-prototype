import {readJsonDocument} from '../../lib/s3Json';
import {ok} from '../../lib/serviceResult';
import {userSpaceBucket} from '../../lib/userSpace';
import {CATALOG_IDENTIFIER_RE} from '../query/query.constants';
import type {ServiceResult} from '../../types/service.types';
import type {UserDirectory} from './userDirectory.types';

/** Where SPEC-146's daily builder publishes. The portal role holds `GetObject` here and nothing else. */
export const DIRECTORY_KEY = '_directory/usernames.json';

/** The only document shape this reader understands. A different one is refused, not guessed at. */
const SUPPORTED_VERSION = 1;

const EMPTY: UserDirectory = {usernames: [], generatedAt: null};

/**
 * Read the published username directory.
 *
 * **A missing document and a corrupt document are both the empty state, not an error.** The
 * only honest thing to do with an unavailable suggestion list is offer no suggestions — an
 * error banner would announce the failure of a feature whose whole promise is that it stays
 * out of the way, and every consumer accepts a name that is not in the list anyway
 * (SPEC-147 FR-005).
 *
 * The bucket name is read at CALL time, never at module load: a module-level
 * `import.meta.env` const is captured before `vi.stubEnv` runs.
 *
 * @returns Always a `ServiceResult`; never throws.
 */
export async function getUserDirectory(): Promise<ServiceResult<UserDirectory>> {
  return readJsonDocument({
    bucket: userSpaceBucket(),
    key: DIRECTORY_KEY,
    parse: (body) => ok(parseDirectory(body)),
    // The directory has never been built, or the daily builder has not run yet.
    onMissing: () => ({success: true, data: EMPTY}),
    fallbackMessage: 'Failed to load the user directory'
  });
}

/** TOTAL: a body that isn't JSON is as empty as one that is JSON of the wrong shape. */
function parseDirectory(body: string | undefined): UserDirectory {
  let parsed: unknown;
  try {
    parsed = body ? JSON.parse(body) : null;
  } catch {
    return EMPTY;
  }
  return toDirectory(parsed);
}

/**
 * Validate a parsed document into a `UserDirectory`, degrading to empty rather than throwing.
 *
 * Every entry is re-checked against `CATALOG_IDENTIFIER_RE` even though SPEC-146's builder
 * already guarantees it. That is not belt-and-braces for its own sake: this array is rendered
 * into the DOM and used to build React keys, and a producer guarantee is not a runtime
 * guarantee — the object is one `aws s3 cp` away from holding anything at all.
 */
function toDirectory(parsed: unknown): UserDirectory {
  if (!parsed || typeof parsed !== 'object') return EMPTY;
  const document = parsed as {version?: unknown; generatedAt?: unknown; usernames?: unknown};

  if (document.version !== SUPPORTED_VERSION) {
    // A shape this reader does not understand is not a shape it should guess at. Named rather
    // than silent, because the fix is a code change here and someone has to know that.
    console.warn(
      `[user-directory] ignoring a document with unsupported version ${String(document.version)} — expected ${SUPPORTED_VERSION}`
    );
    return EMPTY;
  }
  if (!Array.isArray(document.usernames)) return EMPTY;

  const usernames = document.usernames.filter(
    (name: unknown): name is string => typeof name === 'string' && CATALOG_IDENTIFIER_RE.test(name)
  );
  if (usernames.length === 0) return EMPTY;

  return {
    usernames,
    generatedAt: typeof document.generatedAt === 'string' ? document.generatedAt : null
  };
}
