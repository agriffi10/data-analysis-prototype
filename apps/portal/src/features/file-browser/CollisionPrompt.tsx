import { useState } from 'react';
import { Button } from '../../components/Button';
import { Input } from '../../components/Input';

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
      className="mb-4 rounded-lg border border-warning-soft bg-warning-soft p-4 text-sm"
    >
      <div className="flex items-start gap-2">
        <svg
          viewBox="0 0 20 20"
          fill="currentColor"
          className="h-5 w-5 flex-shrink-0 text-warning"
          aria-hidden="true"
        >
          <path
            fillRule="evenodd"
            d="M8.485 2.495c.673-1.167 2.357-1.167 3.03 0l6.28 10.875c.673 1.167-.17 2.625-1.516 2.625H3.72c-1.347 0-2.189-1.458-1.515-2.625L8.485 2.495zM10 6a.75.75 0 01.75.75v3.5a.75.75 0 01-1.5 0v-3.5A.75.75 0 0110 6zm0 9a1 1 0 100-2 1 1 0 000 2z"
            clipRule="evenodd"
          />
        </svg>
        <p className="font-medium text-warning">
          A {kind} named “{name}” already exists.
        </p>
      </div>

      {renaming ? (
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <label className="sr-only" htmlFor="collision-rename">
            New name
          </label>
          <div className="min-w-0 flex-1">
            <Input
              id="collision-rename"
              autoFocus
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && canRename) onRename(trimmed);
              }}
            />
          </div>
          <Button
            variant="primary"
            size="sm"
            disabled={!canRename}
            onClick={() => onRename(trimmed)}
          >
            Save as new name
          </Button>
          <Button variant="ghost" size="sm" onClick={() => setRenaming(false)}>
            Back
          </Button>
        </div>
      ) : (
        <div className="mt-3 flex flex-wrap gap-2">
          <Button
            variant="default"
            size="sm"
            onClick={() => {
              setNewName(name);
              setRenaming(true);
            }}
          >
            Rename
          </Button>
          <Button variant="ghost" size="sm" onClick={onCancel}>
            Cancel
          </Button>
          <Button
            variant="danger"
            size="sm"
            onClick={onOverwrite}
            aria-label={`Overwrite the existing ${name}`}
          >
            Overwrite
          </Button>
        </div>
      )}
    </div>
  );
}
