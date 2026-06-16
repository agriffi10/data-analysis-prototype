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
      className="mb-4 rounded-lg border border-gray-200 bg-white p-4"
    >
      <label
        htmlFor="new-folder-name"
        className="block text-sm font-medium text-gray-700"
      >
        New folder name
      </label>
      <div className="mt-2 flex flex-wrap items-center gap-2">
        <input
          id="new-folder-name"
          autoFocus
          className="flex-1 rounded border border-gray-300 px-2 py-1 text-gray-900 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500"
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
          className="rounded bg-blue-600 px-3 py-1 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
          onClick={submit}
        >
          Create
        </button>
        <button
          className="rounded px-3 py-1 text-sm font-medium text-gray-600 hover:bg-gray-100"
          onClick={onCancel}
        >
          Cancel
        </button>
      </div>
      {showError && (
        <p id="new-folder-error" role="alert" className="mt-2 text-sm text-red-600">
          {validationError}
        </p>
      )}
    </div>
  );
}
