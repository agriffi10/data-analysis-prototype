import {isRootFolderNamed} from './protectedFolders';
import {ARCHIVE_FOLDER, ATHENA_RESULTS_FOLDER, SHARED_TABLES_FOLDER} from '../../lib/appManagedPaths';
import type {S3FolderItem} from '../../types/s3.types';

/**
 * The name of the collapsed group row.
 *
 * It reads as a folder because that is what it is standing in for, but no such prefix
 * exists in S3 and none is ever created: the row is a listing affordance, and every
 * folder inside it keeps the key it has always had.
 */
export const SYSTEM_FOLDER_GROUP_NAME = 'system_settings';

/**
 * The root-level folders collapsed behind the group row, in a personal space and a
 * shared one alike.
 *
 * This is a FIFTH question, and like the four in `protectedFolders` it is deliberately
 * not equal to any of them: *does the app write this folder's contents on the user's
 * behalf?* `athenaresults/` fills with query results, `archive/` with receipts and
 * `shared_tables/` with tables the share pipeline copied in — none of which the user
 * authored. Two of them sort above most user folders (`archive`, `athenaresults`) and the
 * third does not, which is its own argument for gathering them: the app's folders were
 * scattered through the user's rather than collected anywhere.
 *
 * Being written by the app is necessary but not sufficient, because the file-send plane
 * writes `shared_files/{sender}/` too. What separates them is who owns the folder's LAYOUT
 * afterwards, and here the app does and keeps doing: results accumulate, receipts are
 * immutable, and the share pipeline's table files must not acquire neighbours.
 * `saved_queries/` and `shared_files/` are handed over — the user names, moves and deletes
 * what is in them, which is the curation the request's own "cannot edit" clause points at.
 *
 * **The grouping claims no permission.** `shared_tables/` has no IAM Deny anywhere — a
 * user may delete from it, and only the destination picker refuses it — so a reader who
 * took this row as a write boundary would be wrong about one of its three members. What
 * refuses a write is the policy and the per-folder rules beside it, exactly as before;
 * this list moves rows and nothing else.
 */
export const SYSTEM_GROUPED_FOLDERS = [ATHENA_RESULTS_FOLDER, ARCHIVE_FOLDER, SHARED_TABLES_FOLDER] as const;

/**
 * The group row's secondary line, and the half of its accessible name that says what it holds.
 *
 * @param count - How many folders the row is standing in for.
 * @returns The caption, singular or plural.
 */
export function systemFolderGroupCaption(count: number): string {
  return `${count} ${count === 1 ? 'folder' : 'folders'} the app manages for you`;
}

/**
 * Split a listing's folders into the ones shown as ordinary rows and the ones the group
 * row collapses.
 *
 * Root-anchored through `isRootFolderNamed`, so a user's own `archive/` nested inside
 * some other folder stays an ordinary row — and below the space root the grouped list
 * comes back empty, which is what keeps the group row off every other listing without a
 * flag saying so.
 *
 * @param folders - The listing's folders, already filtered of hidden ones.
 * @param rootPrefix - The space root, trailing slash, so the rule holds in a shared space.
 * @returns The ordinary folders and the grouped ones, each in listing order.
 */
export function partitionSystemFolders(
  folders: readonly S3FolderItem[],
  rootPrefix: string
): {ordinary: S3FolderItem[]; grouped: S3FolderItem[]} {
  const ordinary: S3FolderItem[] = [];
  const grouped: S3FolderItem[] = [];
  for (const folder of folders) {
    if (isRootFolderNamed(folder.prefix, rootPrefix, SYSTEM_GROUPED_FOLDERS)) grouped.push(folder);
    else ordinary.push(folder);
  }
  return {ordinary, grouped};
}
