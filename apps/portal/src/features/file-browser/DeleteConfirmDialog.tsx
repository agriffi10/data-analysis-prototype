import { useEffect, useRef } from 'react';
import type { SelectableItem } from './selectionContext';

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
  const cancelRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    cancelRef.current?.focus();
  }, []);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape' && !isDeleting) onCancel();
    }
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [isDeleting, onCancel]);

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
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      onClick={() => {
        if (!isDeleting) onCancel();
      }}
    >
      <div
        role="alertdialog"
        aria-modal="true"
        aria-label="Confirm delete"
        className="w-full max-w-md rounded-lg bg-white p-5 shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <h2 className="text-lg font-semibold text-gray-900">{heading}</h2>

        {count > 1 && (
          <ul className="mt-3 max-h-40 overflow-auto rounded border border-gray-100 bg-gray-50 px-3 py-2 text-sm text-gray-700">
            {described.slice(0, MAX_NAMES).map((d) => (
              <li key={d.name} className="flex items-center gap-2">
                <span aria-hidden="true">{d.isFolder ? '📁' : '📄'}</span>
                <span className="truncate">{d.name}</span>
              </li>
            ))}
            {remaining > 0 && (
              <li className="text-gray-500">…and {remaining} more</li>
            )}
          </ul>
        )}

        {folderCount > 0 && (
          <p className="mt-3 text-sm text-gray-600">
            {folderCount === 1 && count === 1
              ? 'All files and subfolders it contains will be deleted.'
              : 'Selected folders are deleted along with all of their contents.'}
          </p>
        )}

        <p className="mt-3 text-sm font-medium text-red-700">
          This can’t be undone.
        </p>

        <div className="mt-5 flex justify-end gap-2">
          <button
            ref={cancelRef}
            className="rounded px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-100 disabled:opacity-50"
            onClick={onCancel}
            disabled={isDeleting}
          >
            Cancel
          </button>
          <button
            className="rounded bg-red-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-red-700 disabled:opacity-50"
            onClick={onConfirm}
            disabled={isDeleting}
          >
            {isDeleting ? 'Deleting…' : 'Delete'}
          </button>
        </div>
      </div>
    </div>
  );
}
