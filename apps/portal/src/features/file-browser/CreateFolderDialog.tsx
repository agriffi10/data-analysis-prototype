import { useEffect, useRef, useState } from 'react';
import { validateFolderName } from './fileBrowser.service';
import { Button } from '../../components/Button';
import { Input } from '../../components/Input';
import { Modal } from '../../components/Modal';

type Props = {
  onCreate: (name: string) => void;
  onCancel: () => void;
};

// SPEC-016 FR-004: prompt for a new folder name with client-side validation (the
// same rules the service enforces) before any request is issued. Rendered in the
// shared Modal (blur backdrop + focus trap); Enter creates, Escape cancels.
export function CreateFolderDialog({ onCreate, onCancel }: Props) {
  const [name, setName] = useState('');
  const [touched, setTouched] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  const validationError = validateFolderName(name);
  const showError = touched && validationError !== null;

  function submit() {
    setTouched(true);
    if (validateFolderName(name) === null) onCreate(name);
  }

  return (
    <Modal ariaLabel="Create folder" onDismiss={onCancel}>
      <div className="px-5 pb-4 pt-5">
        <h2 className="text-md font-semibold text-text">New folder</h2>

        <div className="mt-4">
          <Input
            id="new-folder-name"
            ref={inputRef}
            label="Folder name"
            required
            aria-required="true"
            value={name}
            error={showError ? validationError : null}
            onChange={(e) => setName(e.target.value)}
            onBlur={() => setTouched(true)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') submit();
            }}
          />
        </div>
      </div>

      <div className="flex justify-end gap-2 rounded-b-lg border-t border-border bg-surface-2 px-5 py-4">
        <Button variant="ghost" onClick={onCancel}>
          Cancel
        </Button>
        <Button variant="primary" onClick={submit}>
          Create
        </Button>
      </div>
    </Modal>
  );
}
