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

// Split a file name into its editable base and its locked extension. The
// extension is everything from the LAST dot; a dotless name or a dotfile
// (leading-dot "hidden" file, e.g. ".env") has no extension — the whole name is
// editable. Folders never have an extension.
function splitFileName(name: string): {base: string; ext: string} {
  const dot = name.lastIndexOf('.');
  if (dot <= 0) return {base: name, ext: ''};
  return {base: name.slice(0, dot), ext: name.slice(dot)};
}

// SPEC-019 FR-002: rename a file or folder. The new name is validated with the
// same rules as create-folder/upload (non-empty trimmed, no `/`, no
// leading/trailing whitespace, no control chars). Modal; Escape cancels; the input
// is prefilled with the current name and the Rename action is disabled until the
// name is valid and changed. For a file WITH an extension, only the base name is
// editable — the extension is held fixed and re-appended on submit so a rename
// can't accidentally change (or drop) the file type.
export function RenameDialog({kind, currentName, isBusy = false, onRename, onCancel}: Props) {
  const {base, ext} = kind === 'file' ? splitFileName(currentName) : {base: currentName, ext: ''};
  const [name, setName] = useState(base);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    inputRef.current?.focus();
    inputRef.current?.select();
  }, []);

  // Recompose the full name from the (trimmed) base plus the locked extension.
  const trimmedBase = name.trim();
  const nextName = trimmedBase.length === 0 ? '' : trimmedBase + ext;
  const validationError = validateFolderName(nextName);
  const unchanged = nextName === currentName;
  const canRename = validationError === null && !unchanged && !isBusy;

  function submit() {
    if (canRename) onRename(nextName);
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
            error={!unchanged ? validationError : null}
            onChange={(e) => setName(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') submit();
            }}
            disabled={isBusy}
          />
          {ext && (
            <p className="mt-1.5 text-xs text-text-3">
              The <span className="font-mono text-text-2">{ext}</span> extension can’t be changed.
            </p>
          )}
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
