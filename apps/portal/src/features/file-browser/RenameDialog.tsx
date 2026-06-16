import { useEffect, useRef, useState } from 'react';
import { validateFolderName } from './fileBrowser.service';

type Props = {
  kind: 'file' | 'folder';
  currentName: string;
  isBusy?: boolean;
  onRename: (newName: string) => void;
  onCancel: () => void;
};

// SPEC-019 FR-002: rename a file or folder. The new name is validated with the
// same rules as create-folder/upload (non-empty trimmed, no `/`, no
// leading/trailing whitespace, no control chars). Modal; Escape cancels; the input
// is prefilled with the current name and the Rename action is disabled until the
// name is valid and changed.
export function RenameDialog({
  kind,
  currentName,
  isBusy = false,
  onRename,
  onCancel,
}: Props) {
  const [name, setName] = useState(currentName);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    inputRef.current?.focus();
    inputRef.current?.select();
  }, []);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape' && !isBusy) onCancel();
    }
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [isBusy, onCancel]);

  const validationError = validateFolderName(name);
  const unchanged = name === currentName;
  const canRename = validationError === null && !unchanged && !isBusy;

  function submit() {
    if (canRename) onRename(name);
  }

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
        aria-label={`Rename ${kind}`}
        className="w-full max-w-md rounded-lg bg-white p-5 shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <h2 className="text-lg font-semibold text-gray-900">
          Rename {kind} “{currentName}”
        </h2>

        <label
          htmlFor="rename-input"
          className="mt-4 block text-sm font-medium text-gray-700"
        >
          New name
        </label>
        <input
          id="rename-input"
          ref={inputRef}
          className="mt-1 w-full rounded border border-gray-300 px-2 py-1 text-gray-900 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500"
          value={name}
          onChange={(e) => setName(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') submit();
          }}
          aria-invalid={validationError !== null}
          aria-describedby={validationError ? 'rename-error' : undefined}
          disabled={isBusy}
        />
        {validationError && name !== currentName && (
          <p id="rename-error" role="alert" className="mt-2 text-sm text-red-600">
            {validationError}
          </p>
        )}

        <div className="mt-5 flex justify-end gap-2">
          <button
            className="rounded px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-100 disabled:opacity-50"
            onClick={onCancel}
            disabled={isBusy}
          >
            Cancel
          </button>
          <button
            className="rounded bg-blue-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
            onClick={submit}
            disabled={!canRename}
          >
            {isBusy ? 'Renaming…' : 'Rename'}
          </button>
        </div>
      </div>
    </div>
  );
}
