import {useEffect, useRef, useState} from 'react';
import {Input} from '../../components/Input';
import {Modal} from '../../components/Modal';
import {DestinationPicker, validateFolderName} from '../file-browser';
import {normalizeCsvName} from './query.format';

// SPEC-055 FR-003: one place a result can be saved — the user's own space or a
// shared space they belong to. Each carries its own bucket + navigation root; the
// protected `athenaresults/` folder is excluded by the picker.
export type DestinationSpace = {
  id: string;
  label: string;
  bucket: string;
  rootPrefix: string; // navigation floor (ends with "/"), e.g. "alice/" or "salesdata/"
  rootLabel: string; // crumb label for the root (hides the username/space segment)
};

type Props = {
  // The destination spaces the user can save into (personal first, then shared).
  spaces: DestinationSpace[];
  defaultName: string; // suggested base name (without extension)
  isBusy?: boolean;
  // destBucket is the chosen space's bucket; destPrefix is a full in-space key
  // prefix (ends with "/"); filename is the final ".csv"-normalized leaf.
  onSave: (args: {destBucket: string; destPrefix: string; filename: string}) => void;
  onCancel: () => void;
};

// SPEC-049 FR-002 + SPEC-055 FR-003: destination-folder picker (reused SPEC-039
// `DestinationPicker`) + a validated file-name field. When the user belongs to
// shared spaces, a space selector chooses which space to browse (personal or a
// shared one); the picker remounts per space (keyed) so its breadcrumb/browse
// state resets cleanly. Save is disabled until a destination is chosen and the
// name is valid.
export function SaveResultsDialog({spaces, defaultName, isBusy = false, onSave, onCancel}: Props) {
  const [name, setName] = useState(defaultName);
  const [spaceId, setSpaceId] = useState(spaces[0]?.id ?? '');
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    inputRef.current?.focus();
    inputRef.current?.select();
  }, []);

  const space = spaces.find((s) => s.id === spaceId) ?? spaces[0];

  // Reuse the file-browser leaf-name validation (no '/', control chars, etc.).
  const nameError = validateFolderName(name.trim());
  const nameValid = nameError === null;

  if (!space) return null;

  return (
    <Modal
      ariaLabel="Save results to my files"
      dismissible={!isBusy}
      onDismiss={onCancel}
      className="flex max-w-lg flex-col px-5 pb-4 pt-5">
      <h2 className="text-md font-semibold text-text">Save results</h2>
      <p className="mt-1 text-sm text-text-2">
        Saves the full result set as a CSV. A <code>.csv</code> extension is added automatically.
      </p>

      <div className="mt-3">
        <Input
          ref={inputRef}
          id="save-results-name"
          label="File name"
          required
          aria-required="true"
          value={name}
          error={name.trim().length > 0 ? nameError : undefined}
          disabled={isBusy}
          onChange={(e) => setName(e.target.value)}
        />
      </div>

      {spaces.length > 1 && (
        <div className="mt-3">
          <label
            htmlFor="save-results-space"
            className="mb-1.5 block text-sm font-medium text-text">
            Save to
          </label>
          <select
            id="save-results-space"
            value={space.id}
            disabled={isBusy}
            onChange={(e) => setSpaceId(e.target.value)}
            className="h-9 w-full rounded-md border border-border bg-surface px-3 text-base text-text focus-visible:border-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent disabled:opacity-45">
            {spaces.map((s) => (
              <option
                key={s.id}
                value={s.id}>
                {s.label}
              </option>
            ))}
          </select>
        </div>
      )}

      <p className="mt-4 mb-1 text-xs font-semibold uppercase tracking-wide text-text-3">Destination folder</p>
      <DestinationPicker
        key={space.id}
        bucket={space.bucket}
        items={[]}
        rootPrefix={space.rootPrefix}
        rootLabel={space.rootLabel}
        currentPrefix={space.rootPrefix}
        isBusy={isBusy}
        allowCurrentParent
        confirmDisabled={!nameValid}
        confirmLabel="Save here"
        busyLabel="Saving…"
        onConfirm={(destPrefix) => onSave({destBucket: space.bucket, destPrefix, filename: normalizeCsvName(name)})}
        onCancel={onCancel}
      />
    </Modal>
  );
}
