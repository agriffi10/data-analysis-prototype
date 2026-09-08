/**
 * The folders the app manages inside a space, and the two functions that turn a folder name into
 * the prefix or prefixes it occupies.
 *
 * Three folders have moved under a real `system_settings/` prefix. Nearly every rule about
 * them is anchored at depth one — `${rootPrefix}${name}/` — so a move to depth two would leave each
 * hand-written comparison silently not matching. This module exists so that the move is an edit
 * here rather than a hunt: the names are declared here and nowhere else, and every anchored
 * construction in the app calls a builder. It lives in `lib/` because two features need it and the
 * archive feature deliberately imports nothing from another feature.
 *
 * **Which builder a caller takes is the design.** `appManagedPrefix` is where a WRITE goes.
 * `appManagedPrefixes` is what every root-anchored COMPARISON calls, and it answers for every
 * location a folder may occupy — two while both homes of a moving folder are admitted, one for
 * anything else. So the move edits both, not one.
 *
 * The SINGULAR builder now resolves a moving folder under `system_settings/`, which is where new
 * writes go; the PLURAL still answers both homes, because the objects written before the switch are
 * still at the old one and every rule has to keep refusing there until they have moved. The two
 * differ on purpose, and they stop differing at the narrowing. A sweep in CI refuses a new
 * declaration or construction outside this file.
 */

/** Athena writes every query's result set here. Visible, browsable, never a write destination. */
export const ATHENA_RESULTS_FOLDER = 'athenaresults';

/**
 * Where the archive plane writes one receipt per archive, and where the user reads the ids a
 * restore needs. VISIBLE and browsable on purpose (a hidden folder cannot be the surface that
 * carries the ids), and read-only in the same breath: `writeLockedPrefix.ts` is the gate.
 */
export const ARCHIVE_FOLDER = 'archive';

/**
 * Where the table-share pipeline copies tables in. Visible, and stays at the space root: these
 * tables were sent to this space and are the user's to edit. Still never a PASTE destination — the
 * pipeline owns the layout, and a table's files acquiring neighbours is how a later projection
 * read starts returning rows nobody wrote.
 */
export const SHARED_TABLES_FOLDER = 'shared_tables';

/**
 * The prefix the three folders above are moving INTO.
 *
 * Nothing is written directly under it, but it is reserved everywhere the three are: never a
 * paste target, never deletable or renamable, never an archive source.
 */
export const SYSTEM_SETTINGS_FOLDER = 'system_settings';

/**
 * The folders that gain a second home while both are admitted.
 *
 * Its own declaration rather than a reuse of the constants as a group, for the same reason the
 * fleet's is: this asks which folders MOVE. `SHARED_TABLES_FOLDER` is deliberately absent — a
 * shared table is data another space sent this one, and the user may edit it, so filing it under
 * the folder the app manages would say the opposite of what is true. It stays at the space root.
 */
export const MOVING_FOLDERS = [ATHENA_RESULTS_FOLDER, ARCHIVE_FOLDER] as const;

/**
 * The prefix an app-managed folder occupies in a space.
 *
 * Branches on `MOVING_FOLDERS` exactly as the plural does. Here that is parity rather than
 * necessity — this tree has no production caller, since the browser writes no app-managed path —
 * but the fleet's twin genuinely needs it, because a folder name reaches it from a domain list
 * whose members mostly do not move. Keeping the two builders one design is what stops a caller
 * arriving later against the wrong one, and the `user_settings` row in the tests holds it.
 *
 * @param rootPrefix - The space root, trailing slash (a username or a shared space's name).
 * @param folder - The folder's name, as declared above or in the protected-folder lists.
 * @returns The folder's prefix, trailing slash — under `system_settings/` for a folder that moves.
 */
export function appManagedPrefix(rootPrefix: string, folder: string): string {
  return (MOVING_FOLDERS as readonly string[]).includes(folder)
    ? `${rootPrefix}${SYSTEM_SETTINGS_FOLDER}/${folder}/`
    : `${rootPrefix}${folder}/`;
}

/**
 * Every root-anchored location a folder may occupy, depth-one first.
 *
 * Two for a member of `MOVING_FOLDERS` while both homes are admitted, one for anything else — so
 * a folder that is not moving never acquires a phantom home, and a rule looping a mixed list stays
 * uniform.
 *
 * **Both elements are literals, and neither is derived from `appManagedPrefix`.** The singular is
 * where a WRITE goes and moves on its own; deriving the plural from it would drag every rule's
 * second home along to a third location instead of leaving it where the data is. The narrowing
 * shrinks this to one element here and touches no caller.
 *
 * @param rootPrefix - The space root, trailing slash. Normalized no more than `appManagedPrefix`
 *   normalizes it, so a caller's bytes come back as handed.
 * @param folder - The folder's name.
 * @returns The folder's locations, depth-one first.
 */
export function appManagedPrefixes(rootPrefix: string, folder: string): readonly string[] {
  return (MOVING_FOLDERS as readonly string[]).includes(folder)
    ? [`${rootPrefix}${folder}/`, `${rootPrefix}system_settings/${folder}/`]
    : [`${rootPrefix}${folder}/`];
}
