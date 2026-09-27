import {useId, useRef, useState} from 'react';
import {validateFileName, validateFolderNameForPlane} from './fileBrowser.service';
import {FormDialog} from '../../components/FormDialog';
import {Input} from '../../components/Input';
import {FIELD_HINT} from '../../components/fieldStyles';

type Props = {
  kind: 'file' | 'folder';
  currentName: string;
  /** The folder the item sits in, which is where the renamed item lands. */
  parentPrefix: string;
  isBusy?: boolean;
  onRename: (newName: string) => void;
  onCancel: () => void;
};

// Split a file name into its editable base and its locked extension. The
// extension is everything from the LAST dot, less any trailing whitespace, which
// no name may end in. A dotless name, a dotfile (leading-dot "hidden" file, e.g.
// ".env"), or a suffix the file-name rules refuse on its own — a bare dot, which
// is no file type, or one holding a control character, which no name can keep —
// has no extension: the whole name is editable. Folders never have an extension.
function splitFileName(name: string): {base: string; ext: string} {
  const dot = name.lastIndexOf('.');
  const ext = name.slice(dot).trimEnd();
  if (dot <= 0 || validateFileName(ext) !== null) return {base: name, ext: ''};
  return {base: name.slice(0, dot), ext};
}

/**
 * Rename a file or folder. The new name is validated with the leaf-name rules (non-empty trimmed,
 * no `/`, no leading/trailing whitespace, no control chars) — a file's by `validateFileName`, a
 * folder's by `validateFolderNameForPlane` against its parent too, so a name that would land on one
 * of the app's own folders is refused before it is submitted. Modal; Escape cancels; the input
 * is prefilled with the current name and the Rename action is disabled until the
 * name is valid and changed. For a file WITH an extension, only the base name is
 * editable — the extension is held fixed and re-appended on submit so a rename
 * can't accidentally change (or drop) the file type, and the field's description
 * says so ahead of any error. A name ending in whitespace (`notes.txt `) keeps
 * `.txt` and loses the whitespace, which no name may end in.
 *
 * @example
 * <RenameDialog kind="folder" currentName="reports" parentPrefix="alice/" isBusy={rename.isPending} onRename={submit} onCancel={close} />
 */
export function RenameDialog({kind, currentName, parentPrefix, isBusy = false, onRename, onCancel}: Props) {
  const {base, ext} = kind === 'file' ? splitFileName(currentName) : {base: currentName, ext: ''};
  const [name, setName] = useState(base);
  const inputRef = useRef<HTMLInputElement>(null);
  const hintId = useId();

  // Recompose the full name from the (trimmed) base plus the locked extension.
  const trimmedBase = name.trim();
  const nextName = trimmedBase.length === 0 ? '' : trimmedBase + ext;
  const validationError =
    kind === 'file' ? validateFileName(nextName) : validateFolderNameForPlane(nextName, parentPrefix);
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
          aria-describedby={ext ? hintId : undefined}
          error={!unchanged ? validationError : null}
          onChange={(e) => setName(e.target.value)}
          disabled={isBusy}
        />
        {ext && (
          <p
            id={hintId}
            className={FIELD_HINT}>
            The <span className="font-mono text-text-2">{ext}</span> extension can’t be changed.
          </p>
        )}
      </div>
    </FormDialog>
  );
}
