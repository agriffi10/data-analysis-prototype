import {appManagedPrefix, ARCHIVE_FOLDER, ATHENA_RESULTS_FOLDER, SHARED_TABLES_FOLDER} from '../../lib/appManagedPaths';
import type {ArchiveItem} from '../../types/archive.types';

/**
 * The space's own portal-managed folders, which may never be an archive source.
 *
 * **This is a MIRROR of `arcommon.config.RESERVED_SOURCE_ROOTS`, and a test asserts the two are
 * equal.** They are not belt-and-braces for each other: the plane's copy is the authority and
 * refuses the request as `reserved_folder`, while this one is the difference between a control
 * that explains itself and a notification arriving after the user has moved on. A divergence
 * shows up as a request the browser cheerfully sends and the plane refuses, which is the failure
 * mode the equality test exists to catch.
 *
 * Two of these — `user_settings` and `_data-quality-reports` — are filtered out of the listing
 * entirely and so can never be selected. They are named anyway, because the list's job is to
 * match the plane's, not to enumerate what is reachable today.
 */
export const ARCHIVE_RESERVED_ROOTS = [
  ARCHIVE_FOLDER,
  ATHENA_RESULTS_FOLDER,
  'user_settings',
  '_data-quality-reports',
  SHARED_TABLES_FOLDER
] as const;

/**
 * Why this selection cannot be archived, or null when it can.
 *
 * **THREE WAYS TO SELECT A RESERVED FOLDER, NOT TWO**, and the third is the one an author leaves
 * out (`arcommon.authz.assert_not_reserved` records it): the folder itself, anything beneath it,
 * and an ANCESTOR that contains it — selecting the space root passes the first two, and the plane
 * expands a folder by listing its prefix, so it would carry `alice/user_settings/` out with
 * everything else and then delete it.
 *
 * Every rule is anchored at the SPACE ROOT, which leaves a user's own `alice/reports/archive/` an
 * ordinary folder they may archive — the same anchoring the undeletable-root refusal uses.
 *
 * @param items - The selection, as the dialog would enqueue it.
 * @param rootPrefix - The space root, trailing slash.
 * @returns The explanation to show on the disabled control, or null.
 */
export function archiveRefusal(items: readonly ArchiveItem[], rootPrefix: string): string | null {
  for (const item of items) {
    // Compared in its trailing-slash form for the ancestor test only: a FILE whose key merely
    // starts the same way — `alice/archived-notes.txt` against `alice/archive/` — is an ordinary
    // file and must still archive.
    const asPrefix = item.key.endsWith('/') ? item.key : `${item.key}/`;
    for (const folder of ARCHIVE_RESERVED_ROOTS) {
      const reserved = appManagedPrefix(rootPrefix, folder);
      if (item.key === reserved.replace(/\/$/, '') || item.key.startsWith(reserved) || reserved.startsWith(asPrefix)) {
        return `“${folder}” is managed for you and can’t be archived.`;
      }
    }
  }
  return null;
}
