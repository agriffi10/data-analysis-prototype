import {useEffect, useRef, useState} from 'react';
import {validateFolderName} from './fileBrowser.service';
import {Button} from '../../components/Button';
import {Input} from '../../components/Input';
import {Modal} from '../../components/Modal';

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
export function RenameDialog({kind, currentName, isBusy = false, onRename, onCancel}: Props) {
  const [name, setName] = useState(currentName);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    inputRef.current?.focus();
    inputRef.current?.select();
  }, []);

  const validationError = validateFolderName(name);
  const unchanged = name === currentName;
  const canRename = validationError === null && !unchanged && !isBusy;

  function submit() {
    if (canRename) onRename(name);
  }

  return (
    <Modal
      ariaLabel={`Rename ${kind}`}
      dismissible={!isBusy}
      onDismiss={onCancel}>
      <div className="px-5 pb-4 pt-5">
        <h2 className="text-md font-semibold text-text">
          Rename {kind} “{currentName}”
        </h2>

        <div className="mt-4">
          <Input
            id="rename-input"
            ref={inputRef}
            label="New name"
            required
            aria-required="true"
            value={name}
            error={validationError && name !== currentName ? validationError : null}
            onChange={(e) => setName(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') submit();
            }}
            disabled={isBusy}
          />
        </div>
      </div>

      <div className="flex justify-end gap-2 rounded-b-lg border-t border-border bg-surface-2 px-5 py-4">
        <Button
          variant="ghost"
          onClick={onCancel}
          disabled={isBusy}>
          Cancel
        </Button>
        <Button
          variant="primary"
          onClick={submit}
          disabled={!canRename}>
          {isBusy ? 'Renaming…' : 'Rename'}
        </Button>
      </div>
    </Modal>
  );
}
