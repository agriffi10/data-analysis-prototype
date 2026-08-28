import {ARCHIVE_FOLDER} from './fileBrowser.constants';
import type {FileSpaceKind} from './useFileSpace';

/**
 * Is this folder one the portal role cannot write into — so the browser must not offer a write?
 *
 * **THE FIRST PREFIX-BASED WRITE GATE IN THIS APP**. Everything before it was
 * a rule about a folder's NAME at the space root (`protectedFolders.ts`); this is a rule about
 * where the user is STANDING, and it is built as a predicate rather than an `if` inside the
 * toolbar because the next read-only prefix will want it.
 *
 * IAM denies `PutObject` / `DeleteObject` / `AbortMultipartUpload` under `archive/` in both space
 * buckets, so without this every attempt produces a bare `AccessDenied` for a
 * rule this application wrote — the situation the undeletable-root refusal exists to prevent for
 * `athenaresults/`.
 *
 * **THE TWO SPACE KINDS ARE DENIED DIFFERENTLY, AND THIS MIRRORS EACH ONE RATHER THAN AVERAGING
 * THEM.** The personal Deny names the caller's own root — `{bucket}/{principalTag}/archive/…` —
 * because in that bucket the prefix IS the principal tag. The shared Deny puts a wildcard where
 * the space name goes, and an S3 resource wildcard matches `/` as well, so it reaches an
 * `archive` folder at ANY depth below the space root. Anchoring both at the root would offer
 * writes into a nested shared `archive/` that IAM refuses; applying the any-depth rule to both
 * would refuse writes into a user's own `alice/backups/archive/` that IAM permits.
 * `archiveWriteLock.test.ts` holds this against the rendered policies, from the other side.
 *
 * @param prefix - The folder currently being viewed, trailing slash (or '' at the root).
 * @param rootPrefix - The space root, trailing slash.
 * @param spaceKind - Which bucket this space lives in, which is what selects the rule.
 * @returns True when writes into this prefix would be denied.
 */
export function isWriteLockedPrefix(prefix: string, rootPrefix: string, spaceKind: FileSpaceKind): boolean {
  const lockedRoot = `${rootPrefix}${ARCHIVE_FOLDER}/`;
  if (prefix === lockedRoot || prefix.startsWith(lockedRoot)) return true;
  if (spaceKind !== 'shared') return false;
  // The shared bucket's wildcard segment matches `/` too, so any `archive` folder below the
  // space root is covered by the same Deny.
  return prefix.startsWith(rootPrefix) && prefix.slice(rootPrefix.length).split('/').includes(ARCHIVE_FOLDER);
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
