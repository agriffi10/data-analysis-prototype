import { useState } from 'react';
import { validateFolderName } from './fileBrowser.service';

type Props = {
  onCreate: (name: string) => void;
  onCancel: () => void;
};

// SPEC-016 FR-004: prompt for a new folder name with client-side validation
// (the same rules the service enforces) before any request is issued.
export function CreateFolderDialog({ onCreate, onCancel }: Props) {
  const [name, setName] = useState('');
  const [touched, setTouched] = useState(false);

  const validationError = validateFolderName(name);
  const showError = touched && validationError !== null;

  function submit() {
    setTouched(true);
    if (validateFolderName(name) === null) onCreate(name);
  }

  return (
    <div
      role="dialog"
      aria-label="Create folder"
      className="mb-4 rounded-lg border border-border bg-surface p-4"
    >
      <label
        htmlFor="new-folder-name"
        className="mb-2 block text-sm font-medium text-text"
      >
        New folder name
      </label>
      <div className="flex items-center gap-2">
        <input
          id="new-folder-name"
          autoFocus
          className="h-9 flex-1 rounded-md border border-border bg-surface px-3 text-base text-text placeholder:text-text-3 focus-visible:border-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/40 disabled:opacity-45"
          value={name}
          onChange={(e) => setName(e.target.value)}
          onBlur={() => setTouched(true)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') submit();
            if (e.key === 'Escape') onCancel();
          }}
          aria-invalid={showError}
          aria-describedby={showError ? 'new-folder-error' : undefined}
        />
        <button
          className="h-9 rounded-md bg-accent px-4 text-base font-medium text-white hover:bg-accent-hover disabled:cursor-not-allowed disabled:opacity-45"
          onClick={submit}
        >
          Create
        </button>
        <button
          className="h-9 rounded-md px-4 text-base font-medium text-text-2 hover:bg-surface-2 hover:text-text disabled:cursor-not-allowed disabled:opacity-45"
          onClick={onCancel}
        >
          Cancel
        </button>
      </div>
      {showError && (
        <p id="new-folder-error" role="alert" className="mt-1.5 text-xs text-danger">
          {validationError}
        </p>
      )}
    </div>
  );
}
