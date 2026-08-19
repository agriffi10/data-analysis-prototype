import {useEffect, useRef, useState} from 'react';
import {Input} from '../../components/Input';
import {Modal} from '../../components/Modal';
import {DestinationPicker, validateFolderName} from '../file-browser';
import {SpaceSelect} from '../../components/SpaceSelect';
import {normalizeCsvName} from './catalog.format';
import type {QuerySpace} from './catalog.types';
import {SECTION_CAPTION} from '../../components/fieldStyles';
import {DIALOG_PANEL, DIALOG_TITLE} from '../../components/dialogChrome';

type Props = {
  /** The destination spaces the user can save into (personal first, then shared). */
  spaces: QuerySpace[];
  /** Suggested base name (without extension). */
  defaultName: string;
  isBusy?: boolean;
  /** `destPrefix` is a full in-space key prefix (ends with "/"); `filename` is the ".csv"-normalized leaf. */
  onSave: (args: {destBucket: string; destPrefix: string; filename: string}) => void;
  onCancel: () => void;
};

/**
 * Destination-folder picker + a validated file-name field for saving results
 * as CSV. When the user belongs to shared spaces, a space selector chooses
 * which space to browse; the picker remounts per space (keyed) so its
 * breadcrumb/browse state resets cleanly. Save is disabled until a
 * destination is chosen and the name is valid.
 */
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
      className={DIALOG_PANEL}>
      <h2 className={DIALOG_TITLE}>Save results</h2>
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

      {/* No `kind` passed, so no " (shared)" suffix — this dialog has never carried one and
          changing what a shipped option says is not this change's business. The difference
          between the two callers is now visible in one line instead of two components. */}
      <SpaceSelect
        id="save-results-space"
        label="Save to"
        spaces={spaces}
        value={space.id}
        disabled={isBusy}
        onChange={setSpaceId}
      />

      <p className={`mt-4 mb-1 ${SECTION_CAPTION}`}>Destination folder</p>
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
