import {
  appManagedPrefixes,
  segmentsHoldAppManaged,
  ARCHIVE_FOLDER,
  ATHENA_RESULTS_FOLDER
} from '../../lib/appManagedPaths';
import type {FileSpaceKind} from './useFileSpace';

/**
 * Is this folder one the portal role cannot write into — so the browser must not offer a write?
 *
 * **THE FIRST PREFIX-BASED WRITE GATE IN THIS APP**. Everything before it was
 * a rule about a folder's NAME at the space root (`protectedFolders.ts`); this is a rule about
 * where the user is STANDING, and it is built as a predicate rather than an `if` inside the
 * toolbar because the next read-only prefix will want it.
 *
 * IAM denies `PutObject` / `DeleteObject` / `AbortMultipartUpload` under the receipt folder in both
 * space buckets, so without this every attempt produces a bare `AccessDenied` for a
 * rule this application wrote — the situation the undeletable-root refusal exists to prevent for
 * the results folder.
 *
 * **THE TWO SPACE KINDS ARE DENIED DIFFERENTLY, AND THIS MIRRORS EACH ONE RATHER THAN AVERAGING
 * THEM.** The personal Deny names the caller's own root — `{bucket}/{principalTag}/system_settings/archive/…`
 * — because in that bucket the prefix IS the principal tag. The shared Deny puts a wildcard where
 * the space name goes, and an S3 resource wildcard matches `/` as well, so it reaches a
 * `system_settings/archive` folder at ANY depth below the space root. Anchoring both at the root
 * would offer writes into a nested shared one that IAM refuses; applying the any-depth rule to both
 * would refuse writes into a user's own `alice/backups/system_settings/archive/` that IAM permits.
 * `archiveWriteLock.test.ts` holds this against the rendered policies, from the other side.
 *
 * **THE SEGMENT MATCHED IS THE PAIR, NOT THE BARE FOLDER NAME.** Until the receipt folder moved,
 * the shared branch below looked for `archive` alone, mirroring a Deny anchored at depth one. That
 * Deny is gone: a depth-one `finance/archive/` is now an ordinary user folder IAM permits writing
 * to, and a branch still keyed on the bare name would refuse it — the over-refusal this docstring
 * names two paragraphs up, arriving through the rule that warned about it. The pair is what the
 * surviving Deny anchors on, so the pair is what this looks for.
 *
 * @param prefix - The folder currently being viewed, trailing slash (or '' at the root).
 * @param rootPrefix - The space root, trailing slash.
 * @param spaceKind - Which bucket this space lives in, which is what selects the rule.
 * @returns True when writes into this prefix would be denied.
 */
export function isWriteLockedPrefix(prefix: string, rootPrefix: string, spaceKind: FileSpaceKind): boolean {
  return isAtOrBelowAppManaged(prefix, rootPrefix, spaceKind, ARCHIVE_FOLDER);
}

/**
 * Is this folder inside the query results folder, where nothing the user writes could be removed?
 *
 * **IAM permits the write here and denies the DELETE**, so this is not part of
 * `isWriteLockedPrefix`: that one mirrors a `PutObject` Deny and says what S3 would refuse. Here S3
 * accepts a folder or an upload and then refuses every attempt to take it away — which is worse
 * than a refusal, and why the browser declines the write itself. The API refuses the same writes,
 * beside its receipt lock, because a disabled button is not a permission. The Denies have the
 * receipt folder's shape, so the rule is the same one pointed at the other folder.
 *
 * @param prefix - The folder currently being viewed, trailing slash (or '' at the root).
 * @param rootPrefix - The space root, trailing slash.
 * @param spaceKind - Which bucket this space lives in, which is what selects the rule.
 * @returns True when anything written into this prefix would be undeletable.
 */
function isQueryResultsPrefix(prefix: string, rootPrefix: string, spaceKind: FileSpaceKind): boolean {
  return isAtOrBelowAppManaged(prefix, rootPrefix, spaceKind, ATHENA_RESULTS_FOLDER);
}

/**
 * Is this folder at or below an app-managed folder, as that bucket's Deny reaches it?
 *
 * Root-anchored for either kind — the personal Deny names the caller's own root — and, in a shared
 * space only, the folder's segments at any depth, because the wildcard there matches `/` too.
 *
 * @param prefix - The folder currently being viewed.
 * @param rootPrefix - The space root.
 * @param spaceKind - The space's kind.
 * @param folder - The app-managed folder's name.
 * @returns True when the prefix is the folder or below it.
 */
function isAtOrBelowAppManaged(prefix: string, rootPrefix: string, spaceKind: FileSpaceKind, folder: string): boolean {
  if (appManagedPrefixes(rootPrefix, folder).some((home) => prefix.startsWith(home))) return true;
  if (spaceKind !== 'shared') return false;
  if (!prefix.startsWith(rootPrefix)) return false;
  return segmentsHoldAppManaged(prefix.slice(rootPrefix.length).split('/'), folder);
}

/**
 * The user-facing reason writes are unavailable here, or null when they are available.
 *
 * A disabled control with no reason is the thing the rule exists to replace, so the gate and its
 * explanation are one function rather than a boolean the caller has to find words for. It answers
 * for both read-only folders, each in its own words; a caller that needs only the receipt folder's
 * lock asks `isWriteLockedPrefix`.
 *
 * @param prefix - The folder currently being viewed.
 * @param rootPrefix - The space root.
 * @param spaceKind - The space's kind.
 * @returns The explanation, or null.
 */
export function writeLockRefusal(prefix: string, rootPrefix: string, spaceKind: FileSpaceKind): string | null {
  if (isWriteLockedPrefix(prefix, rootPrefix, spaceKind))
    return 'The archive folder is read-only — it holds your archive receipts. You can open and download them, but not change them.';
  if (isQueryResultsPrefix(prefix, rootPrefix, spaceKind))
    return 'The query results folder is read-only — your query results are saved here for you. You can open, download and copy them, but not add to or change them.';
  return null;
}
