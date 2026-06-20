import type { SelectableItem } from './selectionContext';
import { ConfirmDialog } from '../../components/ConfirmDialog';

type Props = {
  items: SelectableItem[];
  isDeleting: boolean;
  onConfirm: () => void;
  onCancel: () => void;
};

// The display name + kind for one selected item (file key or folder prefix).
function describe(item: SelectableItem): { name: string; isFolder: boolean } {
  if (item.type === 'file') {
    const name = item.key.split('/').filter(Boolean).pop() ?? item.key;
    return { name, isFolder: false };
  }
  const name = item.prefix.replace(/\/$/, '').split('/').pop() ?? item.prefix;
  return { name, isFolder: true };
}

const MAX_NAMES = 5;

// SPEC-018 FR-004: explicit confirmation before any delete. Names the item(s),
// states the count, warns that deletion is irreversible (no versioning/undo), and
// makes clear that folders are removed with all of their contents. Nothing is
// deleted unless the user confirms. Modal: Escape cancels and focus defaults to
// Cancel so a stray Enter never destroys data.
export function DeleteConfirmDialog({
  items,
  isDeleting,
  onConfirm,
  onCancel,
}: Props) {
  const described = items.map(describe);
  const folderCount = described.filter((d) => d.isFolder).length;
  const count = items.length;

  let heading: string;
  if (count === 1) {
    const only = described[0];
    heading = only.isFolder
      ? `Delete the folder “${only.name}” and everything inside it?`
      : `Delete “${only.name}”?`;
  } else {
    heading = `Delete ${count} items?`;
  }

  const shownNames = described.slice(0, MAX_NAMES).map((d) => d.name);
  const remaining = count - shownNames.length;

  return (
    <ConfirmDialog
      title={heading}
      ariaLabel="Confirm delete"
      confirmLabel="Delete"
      busyLabel="Deleting…"
      busy={isDeleting}
      confirmVariant="danger"
      tone="danger"
      irreversible
      onConfirm={onConfirm}
      onCancel={onCancel}
    >
      {count > 1 && (
        <ul className="mt-3 max-h-36 overflow-auto rounded-md border border-border bg-surface-2 px-3 py-2 text-sm text-text">
          {described.slice(0, MAX_NAMES).map((d) => (
                <li key={d.name} className="flex items-center gap-2 py-0.5">
                  {d.isFolder ? (
                    <svg
                      viewBox="0 0 20 20"
                      fill="currentColor"
                      className="h-4 w-4 flex-shrink-0 text-text-3"
                      aria-hidden="true"
                    >
                      <path d="M2 6a2 2 0 012-2h3.586a1 1 0 01.707.293l1.414 1.414A1 1 0 0010.414 6H16a2 2 0 012 2v7a2 2 0 01-2 2H4a2 2 0 01-2-2V6z" />
                    </svg>
                  ) : (
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
                        d="M13.5 3H7a2 2 0 00-2 2v10a2 2 0 002 2h6a2 2 0 002-2V7.5L13.5 3z"
                      />
                      <path strokeLinecap="round" strokeLinejoin="round" d="M13 3v4.5H17.5" />
                    </svg>
                  )}
                  <span className="truncate">{d.name}</span>
                </li>
              ))}
              {remaining > 0 && (
                <li className="py-0.5 text-text-3">…and {remaining} more</li>
              )}
            </ul>
          )}

          {folderCount > 0 && (
            <p className="mt-3 text-sm text-text-2">
              {folderCount === 1 && count === 1
                ? 'All files and subfolders it contains will be deleted.'
                : 'Selected folders are deleted along with all of their contents.'}
        </p>
      )}
    </ConfirmDialog>
  );
}
