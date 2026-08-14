import {useRef, useState} from 'react';
import {validateFolderName} from './fileBrowser.service';
import {FormDialog} from '../../components/FormDialog';
import {Input} from '../../components/Input';
import {FIELD_HINT} from '../../components/fieldStyles';

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
    <FormDialog
      title={`Rename ${kind} “${currentName}”`}
      ariaLabel={`Rename ${kind}`}
      submitLabel="Rename"
      busy={isBusy}
      busyLabel="Renaming…"
      submitDisabled={!canRename}
      autoFocusRef={inputRef}
      autoFocusSelect
      onSubmit={submit}
      onCancel={onCancel}>
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
          disabled={isBusy}
        />
        {ext && (
          <p className={FIELD_HINT}>
            The <span className="font-mono text-text-2">{ext}</span> extension can’t be changed.
          </p>
        )}
      </div>
    </FormDialog>
  );
}
