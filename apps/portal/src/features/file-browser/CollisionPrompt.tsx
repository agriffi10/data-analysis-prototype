import {useId, useState} from 'react';
import {Button} from '../../components/Button';
import {Input} from '../../components/Input';
import {validateFolderName, validateLeafName} from './fileBrowser.service';

type Props = {
  kind: 'file' | 'folder';
  name: string;
  /** Where a renamed folder lands, when the caller knows it. Ignored for a file. */
  parentPrefix?: string;
  onOverwrite: () => void;
  /**
   * False where replacing what is there does nothing a user could want: a new folder colliding
   * with an existing one would only rewrite its empty marker and leave every file in it. Default true.
   */
  allowOverwrite?: boolean;
  onRename: (newName: string) => void;
  onCancel: () => void;
};

/**
 * Warn-and-confirm when a name already exists. Versioning is off,
 * so overwriting is irreversible — the user must explicitly choose Overwrite or
 * pick a new name. No write happens while this is open.
 *
 * The new name is validated here rather than by each caller, because every caller builds a key by
 * appending it to a prefix: a `/` in it would land the write in a subfolder instead of beside the
 * original. A file gets the leaf rules; a folder gets the folder-name rules, and the ones that
 * depend on the parent only when the caller passes `parentPrefix`.
 *
 * @example
 * <CollisionPrompt kind="file" name="report.csv" onOverwrite={overwrite} onRename={rename} onCancel={cancel} />
 */
export function CollisionPrompt({
  kind,
  name,
  parentPrefix,
  onOverwrite,
  allowOverwrite = true,
  onRename,
  onCancel
}: Props) {
  const [renaming, setRenaming] = useState(false);
  const [newName, setNewName] = useState(name);
  const [touched, setTouched] = useState(false);
  // Several collision rows can be renaming at once, so a fixed id would pair one row's label
  // and error with another row's field.
  const renameId = useId();

  const trimmed = newName.trim();
  const nameError =
    trimmed.length === 0
      ? 'Enter a name.'
      : ((kind === 'folder' ? validateFolderName(trimmed, parentPrefix) : validateLeafName(trimmed, 'File name')) ??
        (trimmed === name ? `Enter a name different from “${name}”.` : null));
  const canRename = nameError === null;
  // Surface why the action is unavailable in text, not just via a disabled
  // button (WCAG 3.3.1 Error Identification).
  const renameError = touched ? (nameError ?? undefined) : undefined;

  return (
    <div
      role="alertdialog"
      aria-label={`${kind === 'file' ? 'File' : 'Folder'} already exists`}
      className="mb-4 rounded-lg border border-warning-soft bg-warning-soft p-4 text-sm">
      <div className="flex items-start gap-2">
        <svg
          viewBox="0 0 20 20"
          fill="currentColor"
          className="h-5 w-5 shrink-0 text-warning"
          aria-hidden="true">
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
          <label
            className="sr-only"
            htmlFor={renameId}>
            New name
          </label>
          <div className="min-w-0 flex-1">
            <Input
              id={renameId}
              autoFocus
              required
              aria-required="true"
              value={newName}
              error={renameError}
              onChange={(e) => {
                setTouched(true);
                setNewName(e.target.value);
              }}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && canRename) onRename(trimmed);
              }}
            />
          </div>
          <Button
            variant="primary"
            size="sm"
            disabled={!canRename}
            onClick={() => onRename(trimmed)}>
            Save as new name
          </Button>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => setRenaming(false)}>
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
            }}>
            Rename
          </Button>
          <Button
            variant="ghost"
            size="sm"
            onClick={onCancel}>
            Cancel
          </Button>
          {allowOverwrite && (
            <Button
              variant="danger"
              size="sm"
              onClick={onOverwrite}
              aria-label={`Overwrite the existing ${name}`}>
              Overwrite
            </Button>
          )}
        </div>
      )}
    </div>
  );
}
