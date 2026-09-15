/**
 * The folders the app manages inside a space, and the two functions that turn a folder name into
 * the prefix or prefixes it occupies.
 *
 * Two folders now live under a real `system_settings/` prefix, and the move is complete: their
 * objects were copied across and the old homes emptied and their fences removed. Nearly every rule
 * about them is anchored — `${rootPrefix}${name}/` — so moving them by hand would have left each
 * comparison silently not matching. This module is what made the move an edit here rather than a
 * hunt: the names are declared here and nowhere else, and every anchored construction in the app
 * calls a builder. It lives in `lib/` because two features need it and the archive feature
 * deliberately imports nothing from another feature.
 *
 * **Which builder a caller takes is still the design, and it outlived the move.**
 * `appManagedPrefix` is where a WRITE goes. `appManagedPrefixes` is what every root-anchored
 * COMPARISON calls, and it answers for every location a folder may occupy — one, now that each has
 * a single home. The two differed only while both homes were admitted; the plural now delegates.
 * A sweep in CI refuses a new declaration or construction outside this file.
 */

/**
 * Athena writes every query's result set here. Visible, browsable, never a write destination: IAM
 * lets the user write here and never delete, so `writeLockedPrefix.ts` refuses the write itself.
 */
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
 * The prefix the two moving folders moved INTO.
 *
 * Nothing is written directly under it, but it is reserved everywhere they are: never a
 * paste target, never deletable or renamable, never an archive source.
 */
export const SYSTEM_SETTINGS_FOLDER = 'system_settings';

/**
 * The folders that live under `SYSTEM_SETTINGS_FOLDER`.
 *
 * Its own declaration rather than a reuse of the constants as a group, for the same reason the
 * fleet's is: this asks which folders MOVED. `SHARED_TABLES_FOLDER` is deliberately absent — a
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
 * Every root-anchored location a folder may occupy.
 *
 * One, for every folder name. The old homes are gone — their objects were copied to
 * `system_settings/` and the sources deleted — so no name has a second location left, and a
 * depth-one `${rootPrefix}archive/` is an ordinary user folder.
 *
 * **It delegates to `appManagedPrefix` rather than repeating its literal.** While both homes were
 * admitted the duplication earned its place: deriving the plural from the singular would have
 * dragged every rule's second home to a third location instead of leaving it where the data still
 * was. With one home that argument is spent, and two literals a few characters apart is a rule
 * written twice. It stays a function, and an array, because every comparison in the app loops over
 * it — which is what made the narrowing an edit here and in one rule module.
 *
 * @param rootPrefix - The space root, trailing slash. Normalized no more than `appManagedPrefix`
 *   normalizes it, so a caller's bytes come back as handed.
 * @param folder - The folder's name.
 * @returns The folder's one location.
 */
export function appManagedPrefixes(rootPrefix: string, folder: string): readonly string[] {
  return [appManagedPrefix(rootPrefix, folder)];
}

/**
 * The path segments an app-managed folder occupies, for an any-depth scan.
 *
 * The companion to `appManagedPrefixes` for rules that are NOT root-anchored. The shared bucket's
 * Denies put a wildcard where the space name goes, and an S3 resource wildcard matches `/` too, so
 * a Deny on `{bucket}` + `/<any>/system_settings/archive/<any>` reaches that folder at any depth
 * below a space root. A rule mirroring one of those Denies scans segments rather than comparing a
 * prefix, and this is what it scans FOR.
 *
 * **It returns a PAIR for a folder that moved, and that is why it exists.** Until the move, every
 * such mirror looked for the bare folder name, because the Deny was anchored one segment deep.
 * Three did — here, in `focommon` and in the API — each a hand-written copy no builder fed, so
 * each kept refusing at the old depth after the Deny narrowed.
 *
 * @param folder - The folder's name.
 * @returns `[SYSTEM_SETTINGS_FOLDER, folder]` for a folder that moved, else `[folder]`.
 */
export function appManagedSegments(folder: string): readonly string[] {
  return (MOVING_FOLDERS as readonly string[]).includes(folder) ? [SYSTEM_SETTINGS_FOLDER, folder] : [folder];
}

/**
 * Do a key's segments hold an app-managed folder at any depth?
 *
 * Consecutiveness is the point: `system_settings/x/archive/` is not the app's folder, and testing
 * the two names separately would say it is. The caller decides which segments to hand over — a
 * file key's last segment is its FILE NAME and is dropped, because a file *called* `archive` is
 * not a file *inside* one, and no Deny whose Resource ends `/archive/*` matches it.
 *
 * @param segments - The key's segments below the space root, already trimmed by the caller.
 * @param folder - The folder's name.
 * @returns True when the folder's segments appear consecutively.
 */
export function segmentsHoldAppManaged(segments: readonly string[], folder: string): boolean {
  const wanted = appManagedSegments(folder);
  return segments.some((_, at) => wanted.every((part, offset) => segments[at + offset] === part));
}
