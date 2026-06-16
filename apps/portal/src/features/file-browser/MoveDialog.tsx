import { useState } from 'react';
import { useFileBrowser } from './useFileBrowser';
import type { SelectableItem } from './selectionContext';
import { Button } from '../../components/Button';

type Props = {
  bucket: string;
  items: SelectableItem[]; // the items being moved
  rootPrefix: string; // navigation floor (user's space root)
  rootLabel?: string; // label for the root crumb (hides the username segment)
  currentPrefix: string; // the items' current parent — not a valid destination
  markerKey?: string;
  isBusy?: boolean;
  onMove: (destPrefix: string) => void;
  onCancel: () => void;
};

type Crumb = { label: string; prefix: string };

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

// SPEC-019 FR-003: destination-folder picker. Lists only folders within the user's
// own space (navigable), excludes the folders being moved (can't descend into
// them), and disables "Move here" at the current parent or inside a moved folder's
// own subtree (no moving a folder into itself).
export function MoveDialog({
  bucket,
  items,
  rootPrefix,
  rootLabel,
  currentPrefix,
  markerKey,
  isBusy = false,
  onMove,
  onCancel,
}: Props) {
  const [browsePrefix, setBrowsePrefix] = useState(rootPrefix);
  const { folders, isLoading, error, hasMore, loadMore, isLoadingMore } =
    useFileBrowser(bucket, browsePrefix, markerKey);

  // Folders being moved can't be navigated into (you can't move a folder inside
  // itself), so hide them from the picker.
  const movedFolderPrefixes = new Set(
    items.filter((i) => i.type === 'folder').map((i) => i.prefix),
  );
  const navigableFolders = folders.filter(
    (f) => !movedFolderPrefixes.has(f.prefix),
  );

  // "Move here" is invalid at the current parent (a no-op) or anywhere inside a
  // moved folder's own subtree.
  const intoOwnSubtree = [...movedFolderPrefixes].some((p) =>
    browsePrefix.startsWith(p),
  );
  const atCurrentParent = browsePrefix === currentPrefix;
  const canMoveHere = !isBusy && !atCurrentParent && !intoOwnSubtree;
  const disabledReason = atCurrentParent
    ? "These items are already here."
    : intoOwnSubtree
      ? "You can't move a folder into itself."
      : undefined;

  const crumbs = crumbsFor(browsePrefix, rootPrefix, rootLabel);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      onClick={() => {
        if (!isBusy) onCancel();
      }}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Move to folder"
        className="flex w-full max-w-lg flex-col rounded-lg bg-surface shadow-lg"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="px-5 pb-4 pt-5">
          <h2 className="text-md font-semibold text-text">
            Move {items.length} {items.length === 1 ? 'item' : 'items'}
          </h2>

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
        </div>

        {/* Folder picker */}
        <div className="px-5 pb-4">
          <div className="max-h-64 overflow-y-auto rounded-md border border-border bg-surface">
            {isLoading && (
              <p role="status" aria-label="Loading" className="py-4 text-center text-sm text-text-3">
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

        <div className="flex justify-end gap-2 rounded-b-lg border-t border-border bg-surface-2 px-5 py-4">
          <Button variant="ghost" onClick={onCancel} disabled={isBusy}>
            Cancel
          </Button>
          <Button
            variant="primary"
            onClick={() => onMove(browsePrefix)}
            disabled={!canMoveHere}
          >
            {isBusy ? 'Moving…' : 'Move here'}
          </Button>
        </div>
      </div>
    </div>
  );
}
