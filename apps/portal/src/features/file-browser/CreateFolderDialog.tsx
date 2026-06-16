import { useState } from 'react';
import { validateFolderName } from './fileBrowser.service';
import { Button } from '../../components/Button';
import { Input } from '../../components/Input';

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
      <Input
        id="new-folder-name"
        label="New folder name"
        autoFocus
        value={name}
        error={showError ? validationError : null}
        onChange={(e) => setName(e.target.value)}
        onBlur={() => setTouched(true)}
        onKeyDown={(e) => {
          if (e.key === 'Enter') submit();
          if (e.key === 'Escape') onCancel();
        }}
      />
      <div className="mt-2 flex gap-2">
        <Button variant="primary" onClick={submit}>
          Create
        </Button>
        <Button variant="ghost" onClick={onCancel}>
          Cancel
        </Button>
      </div>
    </div>
  );
}
