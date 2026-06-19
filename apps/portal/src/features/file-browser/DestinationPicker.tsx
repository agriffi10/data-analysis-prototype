import { useState } from 'react';
import { useFileBrowser } from './useFileBrowser';
import type { SelectableItem } from './selectionContext';
import { Button } from '../../components/Button';

// SPEC-032: the protected results folder. It is UI-locked, so it is never offered
// as a destination for a move or copy (writing into it is disallowed). Matched on
// the leaf segment of a prefix within the user's own space.
const PROTECTED_FOLDER = 'athenaresults';

type Props = {
  bucket: string;
  items: SelectableItem[]; // the items being moved/copied
  rootPrefix: string; // navigation floor (user's space root)
  rootLabel?: string; // label for the root crumb (hides the username segment)
  currentPrefix: string; // the items' current parent
  markerKey?: string;
  isBusy?: boolean;
  // Whether the items' current parent is a valid destination. Move forbids it
  // (a no-op); Copy allows it (→ same-folder auto-number, SPEC-039 FR-003).
  allowCurrentParent?: boolean;
  confirmLabel: string; // e.g. "Move here" / "Copy here"
  busyLabel: string; // e.g. "Moving…" / "Copying…"
  // Message shown when the confirm action is blocked inside an operated folder's
  // own subtree (the verb differs: "move" vs "copy").
  selfMessage?: string;
  onConfirm: (destPrefix: string) => void;
  onCancel: () => void;
};

type Crumb = { label: string; prefix: string };

// Is this folder prefix the protected results folder at the user's root
// (`{root}athenaresults/`)? Only the user-root results folder is locked.
function isProtectedFolder(folderPrefix: string, rootPrefix: string): boolean {
  return folderPrefix === `${rootPrefix}${PROTECTED_FOLDER}/`;
}

// Parent of a browse prefix, clamped to the navigation floor so the picker can
// never climb above the user's own space: `alice/a/b/` → `alice/a/`, and
// `alice/a/` → `alice/` (the root). Used by the ".." up-navigation row.
function parentOf(prefix: string, rootPrefix: string): string {
  const parts = prefix.replace(/\/$/, '').split('/');
  parts.pop();
  const parent = parts.length > 0 ? parts.join('/') + '/' : '';
  return parent.length < rootPrefix.length ? rootPrefix : parent;
}

// Clamped breadcrumb from rootPrefix down to the browsed prefix (the username
// segment is never shown — rootLabel stands in for the root crumb).
function crumbsFor(
  browsePrefix: string,
  rootPrefix: string,
  rootLabel?: string,
): Crumb[] {
  const rootParts = rootPrefix.split('/').filter(Boolean);
  const label = rootLabel ?? rootParts[rootParts.length - 1] ?? 'Home';
  const crumbs: Crumb[] = [{ label, prefix: rootPrefix }];
  if (browsePrefix === rootPrefix) return crumbs;

  const sub = browsePrefix.split('/').filter(Boolean).slice(rootParts.length);
  sub.forEach((part, i) => {
    crumbs.push({
      label: part,
      prefix: [...rootParts, ...sub.slice(0, i + 1)].join('/') + '/',
    });
  });
  return crumbs;
}

// SPEC-039 FR-006: the shared destination-folder picker used by both Move
// (SPEC-019) and Copy. Lists only folders within the user's own space
// (navigable), excludes the folders being operated on (can't descend into them)
// and the protected `athenaresults/` folder (never a write destination), and
// disables the confirm button inside an operated folder's own subtree (no
// moving/copying a folder into itself). Whether the items' current parent is a
// valid destination is caller-controlled (`allowCurrentParent`): Move forbids it,
// Copy allows it (same-folder auto-number).
export function DestinationPicker({
  bucket,
  items,
  rootPrefix,
  rootLabel,
  currentPrefix,
  markerKey,
  isBusy = false,
  allowCurrentParent = false,
  confirmLabel,
  busyLabel,
  selfMessage = "You can't copy a folder into itself.",
  onConfirm,
  onCancel,
}: Props) {
  const [browsePrefix, setBrowsePrefix] = useState(rootPrefix);
  const { folders, isLoading, error, hasMore, loadMore, isLoadingMore } =
    useFileBrowser(bucket, browsePrefix, markerKey);

  // Folders being operated on can't be navigated into (you can't move/copy a
  // folder inside itself), so hide them from the picker. The protected results
  // folder is also hidden — it is never a valid write destination (SPEC-032).
  const operatedFolderPrefixes = new Set(
    items.filter((i) => i.type === 'folder').map((i) => i.prefix),
  );
  const navigableFolders = folders.filter(
    (f) =>
      !operatedFolderPrefixes.has(f.prefix) &&
      !isProtectedFolder(f.prefix, rootPrefix),
  );

  // The confirm action is invalid anywhere inside an operated folder's own
  // subtree, and (for Move) at the current parent.
  const intoOwnSubtree = [...operatedFolderPrefixes].some((p) =>
    browsePrefix.startsWith(p),
  );
  const atCurrentParent = browsePrefix === currentPrefix;
  const currentParentBlocked = atCurrentParent && !allowCurrentParent;
  const canConfirm = !isBusy && !currentParentBlocked && !intoOwnSubtree;
  const disabledReason = currentParentBlocked
    ? 'These items are already here.'
    : intoOwnSubtree
      ? selfMessage
      : undefined;

  const crumbs = crumbsFor(browsePrefix, rootPrefix, rootLabel);

  return (
    <>
      {/* Destination breadcrumb */}
      <nav aria-label="destination breadcrumb" className="mt-1">
        <ol className="flex flex-wrap items-center gap-1 text-sm text-text-2">
          {crumbs.map((crumb, i) => {
            const isLast = i === crumbs.length - 1;
            return (
              <li key={crumb.prefix} className="flex items-center gap-1">
                {i > 0 && (
                  <span aria-hidden="true" className="mx-0.5 text-text-3">
                    /
                  </span>
                )}
                {isLast ? (
                  <span aria-current="page" className="font-medium text-text">
                    {crumb.label}
                  </span>
                ) : (
                  <button
                    className="hover:text-text hover:underline"
                    onClick={() => setBrowsePrefix(crumb.prefix)}
                  >
                    {crumb.label}
                  </button>
                )}
              </li>
            );
          })}
        </ol>
      </nav>

      {/* Folder picker */}
      <div className="mt-4">
        <div className="max-h-64 overflow-y-auto rounded-md border border-border bg-surface">
          {isLoading && (
            <p
              role="status"
              aria-label="Loading"
              className="py-4 text-center text-sm text-text-3"
            >
              Loading…
            </p>
          )}
          {!isLoading && error !== null && (
            <p role="alert" className="p-4 text-sm text-danger">
              {error}
            </p>
          )}
          {!isLoading && error === null && navigableFolders.length === 0 && (
            <p className="py-4 text-center text-sm text-text-3">
              No subfolders here.
            </p>
          )}
          <ul aria-label="Destination folders">
            {/* Parent-folder row (SPEC-026 FR-008): climb back up toward the
                root. Shown only below the navigation floor. */}
            {browsePrefix !== rootPrefix && (
              <li>
                <button
                  className="flex h-10 w-full cursor-pointer items-center gap-2 px-3 text-left text-sm text-text-2 hover:bg-surface-2 focus-visible:outline-none"
                  onClick={() => setBrowsePrefix(parentOf(browsePrefix, rootPrefix))}
                  aria-label="Go up to parent folder"
                >
                  <svg
                    viewBox="0 0 20 20"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="1.5"
                    className="h-4 w-4 flex-shrink-0 text-text-3"
                    aria-hidden="true"
                  >
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      d="M4 10l4-4m-4 4l4 4m-4-4h8a4 4 0 014 4v2"
                    />
                  </svg>
                  <span className="flex-1 truncate">..</span>
                </button>
              </li>
            )}
            {navigableFolders.map((folder) => (
              <li key={folder.prefix}>
                <button
                  className="flex h-10 w-full cursor-pointer items-center gap-2 px-3 text-left text-sm text-text hover:bg-surface-2 focus-visible:outline-none"
                  onClick={() => setBrowsePrefix(folder.prefix)}
                  aria-label={`Open folder ${folder.name}`}
                >
                  <svg
                    viewBox="0 0 20 20"
                    fill="currentColor"
                    className="h-4 w-4 flex-shrink-0 text-accent"
                    aria-hidden="true"
                  >
                    <path d="M2 6a2 2 0 012-2h3.586a1 1 0 01.707.293l1.414 1.414A1 1 0 0010.414 6H16a2 2 0 012 2v7a2 2 0 01-2 2H4a2 2 0 01-2-2V6z" />
                  </svg>
                  <span className="flex-1 truncate">{folder.name}</span>
                </button>
              </li>
            ))}
          </ul>
          {hasMore && (
            <div className="p-2 text-center">
              <button
                className="h-8 rounded-md px-3 text-sm text-text-2 hover:bg-surface-2 disabled:opacity-45"
                onClick={loadMore}
                disabled={isLoadingMore}
              >
                {isLoadingMore ? 'Loading…' : 'Load more'}
              </button>
            </div>
          )}
        </div>

        {disabledReason && (
          <p className="mt-2 text-xs text-text-3">{disabledReason}</p>
        )}
      </div>

      <div className="-mx-5 -mb-4 mt-4 flex justify-end gap-2 rounded-b-lg border-t border-border bg-surface-2 px-5 py-4">
        <Button variant="ghost" onClick={onCancel} disabled={isBusy}>
          Cancel
        </Button>
        <Button
          variant="primary"
          onClick={() => onConfirm(browsePrefix)}
          disabled={!canConfirm}
        >
          {isBusy ? busyLabel : confirmLabel}
        </Button>
      </div>
    </>
  );
}
