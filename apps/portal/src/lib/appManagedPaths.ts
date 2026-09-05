/**
 * The folders the app manages inside a space, and the ONE function that turns a folder name
 * into the prefix it occupies.
 *
 * Three folders are about to move under a real `system_settings/` prefix. Nearly every rule about
 * them is anchored at depth one — `${rootPrefix}${name}/` — so a move to depth two would leave each
 * hand-written comparison silently not matching. This module exists so that the move is one edit
 * to `appManagedPrefix` rather than a hunt: the names are declared here and nowhere else, and every
 * anchored construction in the app calls the builder. It lives in `lib/` because two features need
 * it and the archive feature deliberately imports nothing from another feature.
 *
 * Today the builder is the depth-one form and every folder resolves to exactly the string it
 * always has. A sweep in CI refuses a new declaration or construction outside this file.
 */

/** Athena writes every query's result set here. Visible, browsable, never a write destination. */
export const ATHENA_RESULTS_FOLDER = 'athenaresults';

/**
 * Where the archive plane writes one receipt per archive, and where the user reads the ids a
 * restore needs. VISIBLE and browsable on purpose (a hidden folder cannot be the surface that
 * carries the ids), and read-only in the same breath: `writeLockedPrefix.ts` is the gate.
 */
export const ARCHIVE_FOLDER = 'archive';

/** Where the table-share pipeline copies tables in. Visible; never a write destination. */
export const SHARED_TABLES_FOLDER = 'shared_tables';

/**
 * The prefix an app-managed folder occupies in a space.
 *
 * @param rootPrefix - The space root, trailing slash (a username or a shared space's name).
 * @param folder - The folder's name, as declared above or in the protected-folder lists.
 * @returns The folder's prefix, trailing slash.
 */
export function appManagedPrefix(rootPrefix: string, folder: string): string {
  return `${rootPrefix}${folder}/`;
}
