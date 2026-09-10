import {appManagedPrefixes, segmentsHoldAppManaged, ARCHIVE_FOLDER} from '../../lib/appManagedPaths';
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
  const lockedRoots = appManagedPrefixes(rootPrefix, ARCHIVE_FOLDER);
  if (lockedRoots.some((lockedRoot) => prefix === lockedRoot || prefix.startsWith(lockedRoot))) return true;
  if (spaceKind !== 'shared') return false;
  // The shared bucket's wildcard segment matches `/` too, so a `system_settings/archive` pair at
  // any depth below the space root is covered by the same Deny.
  if (!prefix.startsWith(rootPrefix)) return false;
  return segmentsHoldAppManaged(prefix.slice(rootPrefix.length).split('/'), ARCHIVE_FOLDER);
}

/**
 * The user-facing reason writes are unavailable here, or null when they are available.
 *
 * A disabled control with no reason is the thing the rule exists to replace, so the gate and its
 * explanation are one function rather than a boolean the caller has to find words for.
 *
 * @param prefix - The folder currently being viewed.
 * @param rootPrefix - The space root.
 * @param spaceKind - The space's kind.
 * @returns The explanation, or null.
 */
export function writeLockRefusal(prefix: string, rootPrefix: string, spaceKind: FileSpaceKind): string | null {
  return isWriteLockedPrefix(prefix, rootPrefix, spaceKind)
    ? 'The archive folder is read-only — it holds your archive receipts. You can open and download them, but not change them.'
    : null;
}
