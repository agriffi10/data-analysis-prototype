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
        className="w-full max-w-md rounded-lg bg-surface shadow-lg"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="px-5 pb-4 pt-5">
          <h2 className="text-md font-semibold text-text">
            Rename {kind} “{currentName}”
          </h2>

          <label
            htmlFor="rename-input"
            className="mt-4 block text-sm font-medium text-text"
          >
            New name
          </label>
          <input
            id="rename-input"
            ref={inputRef}
            className="mt-1.5 h-9 w-full rounded-md border border-border bg-surface px-3 text-base text-text placeholder:text-text-3 focus-visible:border-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/40 disabled:opacity-45"
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
            <p id="rename-error" role="alert" className="mt-1.5 text-xs text-danger">
              {validationError}
            </p>
          )}
        </div>

        <div className="flex justify-end gap-2 rounded-b-lg border-t border-border bg-surface-2 px-5 py-4">
          <button
            className="h-9 rounded-md px-4 text-base font-medium text-text-2 hover:bg-surface-2 hover:text-text disabled:cursor-not-allowed disabled:opacity-45"
            onClick={onCancel}
            disabled={isBusy}
          >
            Cancel
          </button>
          <button
            className="h-9 rounded-md bg-accent px-4 text-base font-medium text-white hover:bg-accent-hover disabled:cursor-not-allowed disabled:opacity-45"
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
