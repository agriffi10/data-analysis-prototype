import {apiRequest} from '../../lib/apiClient';
import {CATALOG_IDENTIFIER_RE} from '../../lib/catalogIdentifier';
import type {ServiceResult} from '../../types/service.types';
import type {UserDirectory} from './userDirectory.types';

const EMPTY: UserDirectory = {usernames: [], generatedAt: null};

/**
 * Read the published username directory.
 *
 * **A missing document and a corrupt document are both the empty state, not an error.** The
 * only honest thing to do with an unavailable suggestion list is offer no suggestions — an
 * error banner would announce the failure of a feature whose whole promise is that it stays
 * out of the way, and every consumer accepts a name that is not in the list anyway. That
 * judgement now lives on the server, which answers 200 with an empty list for a missing,
 * unreadable or unrecognised document; what reaches here as a failure is a real fault.
 *
 * The API's origin is read at CALL time, never at module load: a runtime document is not in
 * hand until the bootstrap resolves it.
 *
 * @returns Always a `ServiceResult`; never throws.
 */
export async function getUserDirectory(): Promise<ServiceResult<UserDirectory>> {
  const result = await apiRequest('userDirectory.get');
  if (!result.success) return result;
  return {success: true, data: toDirectory(result.data)};
}

/**
 * Narrow the response into a `UserDirectory`, degrading to empty rather than throwing.
 *
 * Every entry is re-checked against `CATALOG_IDENTIFIER_RE` even though the API already
 * filters them. That is not belt-and-braces for its own sake: this array is rendered into
 * the DOM and used to build React keys, and a producer guarantee is not a runtime guarantee.
 * The API is now a *second* producer, which is one more thing that can be wrong, not one
 * fewer — and the check costs a pass over a list that is capped anyway.
 */
function toDirectory(response: {usernames: string[]; generatedAt: string | null}): UserDirectory {
  const usernames = (Array.isArray(response.usernames) ? response.usernames : []).filter(
    (name: unknown): name is string => typeof name === 'string' && CATALOG_IDENTIFIER_RE.test(name)
  );
  if (usernames.length === 0) return EMPTY;

  return {
    usernames,
    generatedAt: typeof response.generatedAt === 'string' ? response.generatedAt : null
  };
}
