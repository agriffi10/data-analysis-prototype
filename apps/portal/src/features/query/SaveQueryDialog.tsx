import {useRef, useState} from 'react';
import {FormDialog} from '../../components/FormDialog';
import {Input} from '../../components/Input';
import {validateSavedQueryName} from './savedQueries.service';

type Props = {
  /** '' for a new save; the linked file's name on re-save (pre-filled and selected). */
  initialName: string;
  /** Where the file will land, named so the user knows before they replace anything. */
  spaceLabel: string;
  onSave: (name: string) => void;
  onCancel: () => void;
};

/**
 * Name prompt for saving the active tab's SQL into a space's `saved_queries/` folder.
 *
 * EVERY save asks, a linked tab's included — a change from SPEC-043's silent write-back
 * to the query it was opened from. A user about to overwrite a file should be told which
 * file, in which space, before it happens.
 *
 * The collision is no longer detected here: SPEC-043 scanned the in-memory list
 * case-insensitively, which stopped being sound once the list is paginated and the
 * target space may not be the one on screen. `writeSavedQuery` HEADs the exact key and
 * the host turns its `Collision` failure into the replace confirm.
 */
export function SaveQueryDialog({initialName, spaceLabel, onSave, onCancel}: Props) {
  const [name, setName] = useState(initialName);
  const inputRef = useRef<HTMLInputElement>(null);

  const trimmed = name.trim();
  const nameError = trimmed.length > 0 ? validateSavedQueryName(trimmed) : null;
  const canSave = trimmed.length > 0 && nameError === null;

  return (
    <FormDialog
      title="Save query"
      ariaLabel="Save query"
      submitLabel="Save"
      submitDisabled={!canSave}
      autoFocusRef={inputRef}
      autoFocusSelect
      onSubmit={() => {
        if (canSave) onSave(trimmed);
      }}
      onCancel={onCancel}>
      {/* `mt-3` reproduces the gap the old markup got from an `mb-3` on the heading. */}
      <div className="mt-3">
        <Input
          ref={inputRef}
          id="saved-query-name"
          label="Name"
          required
          aria-required="true"
          value={name}
          error={nameError ?? undefined}
          placeholder="e.g. Monthly revenue"
          onChange={(e) => setName(e.target.value)}
        />
        <p className="mt-2 text-sm text-text-3">
          Saved as a <code>.sql</code> file in {spaceLabel} → <code>saved_queries</code>.
        </p>
      </div>
    </FormDialog>
  );
}
