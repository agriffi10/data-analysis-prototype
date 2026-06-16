import { useState } from 'react';

type Props = {
  kind: 'file' | 'folder';
  name: string;
  onOverwrite: () => void;
  onRename: (newName: string) => void;
  onCancel: () => void;
};

// SPEC-016 FR-003: warn-and-confirm when a name already exists. Versioning is off,
// so overwriting is irreversible — the user must explicitly choose Overwrite or
// pick a new name. No write happens while this is open.
export function CollisionPrompt({
  kind,
  name,
  onOverwrite,
  onRename,
  onCancel,
}: Props) {
  const [renaming, setRenaming] = useState(false);
  const [newName, setNewName] = useState(name);

  const trimmed = newName.trim();
  const canRename = trimmed.length > 0 && trimmed !== name;

  return (
    <div
      role="alertdialog"
      aria-label={`${kind === 'file' ? 'File' : 'Folder'} already exists`}
      className="mb-4 rounded-lg border border-amber-300 bg-amber-50 p-4 text-sm text-amber-900"
    >
      <p className="font-medium">
        A {kind} named “{name}” already exists.
      </p>

      {renaming ? (
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <label className="sr-only" htmlFor="collision-rename">
            New name
          </label>
          <input
            id="collision-rename"
            autoFocus
            className="flex-1 rounded border border-gray-300 px-2 py-1 text-gray-900 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500"
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && canRename) onRename(trimmed);
            }}
          />
          <button
            className="rounded bg-blue-600 px-3 py-1 font-medium text-white hover:bg-blue-700 disabled:opacity-50"
            disabled={!canRename}
            onClick={() => onRename(trimmed)}
          >
            Save as new name
          </button>
          <button
            className="rounded px-3 py-1 font-medium text-gray-600 hover:bg-gray-100"
            onClick={() => setRenaming(false)}
          >
            Back
          </button>
        </div>
      ) : (
        <div className="mt-3 flex flex-wrap gap-2">
          <button
            className="rounded bg-amber-600 px-3 py-1 font-medium text-white hover:bg-amber-700"
            onClick={onOverwrite}
          >
            Overwrite
          </button>
          <button
            className="rounded border border-amber-400 px-3 py-1 font-medium text-amber-800 hover:bg-amber-100"
            onClick={() => {
              setNewName(name);
              setRenaming(true);
            }}
          >
            Rename
          </button>
          <button
            className="rounded px-3 py-1 font-medium text-gray-600 hover:bg-gray-100"
            onClick={onCancel}
          >
            Cancel
          </button>
        </div>
      )}
    </div>
  );
}
