import type {QuerySpace} from '../catalog/catalog.types';

// The source side of the Data Explorer: which space holds which
// Glue database, and what a `/explore` deep link resolves to. Pure functions, separate from
// the picker and the hook that use them, because the precedence rule below is the part worth
// asserting directly rather than through a rendered tree.

/**
 * The Glue database a space's tables live in.
 *
 * A space maps to exactly ONE database in this app — the personal space to the username, a
 * shared space to its own name (`useConnections` builds both, and `QuerySpace.id` carries the
 * shared name verbatim). That is why the picker asks for a space and then shows tables: a
 * database step would offer one option, which the gating rule declines to render for the share
 * dialog's recipient kind. The `db` deep-link parameter survives as a CROSS-CHECK, not a
 * choice — a link naming a database that is not this space's names nothing reachable.
 *
 * @param space - The space, as `useQuerySpaces` returns it.
 * @param username - The signed-in username; the personal space's database name.
 * @returns The Glue database name.
 */
export function spaceDatabase(space: QuerySpace, username: string): string {
  return space.id === 'personal' ? username : space.id;
}

/** The `/explore` query string, as the route receives it. */
export type ExploreParams = {
  space: string | null;
  db: string | null;
  table: string | null;
};

/** A resolved, reachable source: everything `openTab` needs. */
export type ExploreTarget = {
  spaceId: string;
  database: string;
  table: string;
};

/**
 * What a link resolved to.
 *
 * `denied` and `none` are deliberately different: `denied` is a space this user cannot
 * reach and renders an explicit refusal, while `none` is an absent or unusable link and
 * renders the picker, which is what a user who typed `/explore` sees anyway.
 */
export type ExploreResolution = {status: 'none'} | {status: 'denied'} | {status: 'ready'; target: ExploreTarget};

/**
 * Resolve `?space=&db=&table=` against the spaces this user can actually reach.
 *
 * **PRECEDENCE IS LOAD-BEARING**: the actor's own username always
 * resolves personal, and shared names are consulted only when the parameter differs from it.
 * A user whose username matches a shared space they belong to would otherwise be sent to the
 * shared bucket's database — reading a colleague's catalog under their own name, or, more
 * likely, failing on a database that is theirs.
 *
 * It resolves from the LIST, never by probing: a space absent from `spaces` is refused here
 * and the caller issues no Glue call for it, so an inaccessible database and a nonexistent
 * one are indistinguishable from outside (the rule, applied to the catalog).
 *
 * @param params - The three search parameters, each null when absent.
 * @param spaces - Spaces the user can reach, as the VIEW has already filtered them.
 * @param username - The signed-in username; '' when signed out.
 * @param sharedEnabled - Is `sharedWorkspaces` on? With it off `space` is not read at all —
 *   never resolved-then-fallen-back, because a "we sent you somewhere else" banner over a
 *   parameter that was never consulted would be a lie.
 * @returns The resolution: a target, a refusal, or nothing to do.
 */
export function resolveExploreParams(
  params: ExploreParams,
  spaces: readonly QuerySpace[],
  username: string,
  sharedEnabled: boolean
): ExploreResolution {
  const spaceParam = sharedEnabled ? params.space : null;
  // A link is a triple. Two thirds of one names no table, and the picker is the honest
  // answer to it — the rule is explicit that a malformed parameter is not an error state.
  if (!params.db || !params.table) return {status: 'none'};

  const space = resolveSpace(spaceParam, spaces, username);
  if (!space) return {status: spaceParam ? 'denied' : 'none'};
  if (spaceDatabase(space, username) !== params.db) return {status: 'none'};

  return {status: 'ready', target: {spaceId: space.id, database: params.db, table: params.table}};
}

/**
 * The space a `?space=` value names, or undefined when it names none this user can reach.
 *
 * @param spaceParam - The parameter, or null when absent or not read.
 * @param spaces - Spaces the user can reach.
 * @param username - The signed-in username.
 * @returns The space, or undefined for an unreachable one.
 */
function resolveSpace(
  spaceParam: string | null,
  spaces: readonly QuerySpace[],
  username: string
): QuerySpace | undefined {
  const personal = spaces.find((s) => s.id === 'personal');
  if (!spaceParam) return personal;
  if (spaceParam === 'personal' || (username && spaceParam === username)) return personal;
  return spaces.find((s) => s.id === spaceParam);
}
