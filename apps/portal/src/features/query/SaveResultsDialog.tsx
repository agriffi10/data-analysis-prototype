import { useEffect, useRef, useState } from 'react';
import { Input } from '../../components/Input';
import { Modal } from '../../components/Modal';
import { DestinationPicker, validateFolderName } from '../file-browser';
import { normalizeCsvName } from './query.format';

type Props = {
  bucket: string;
  rootPrefix: string; // the user's space root (navigation floor), e.g. "alice/"
  rootLabel?: string;
  defaultName: string; // suggested base name (without extension)
  isBusy?: boolean;
  // destPrefix is a full in-space key prefix (ends with "/"); filename is the
  // final ".csv"-normalized leaf.
  onSave: (args: { destPrefix: string; filename: string }) => void;
  onCancel: () => void;
};

// SPEC-049 FR-002: destination-folder picker (reused SPEC-039 `DestinationPicker`,
// scoped to the user's own space; the protected `athenaresults/` folder is already
// excluded by the picker) + a validated file-name field. Save is disabled until a
// destination is chosen and the name is valid.
export function SaveResultsDialog({
  bucket,
  rootPrefix,
  rootLabel,
  defaultName,
  isBusy = false,
  onSave,
  onCancel,
}: Props) {
  const [name, setName] = useState(defaultName);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    inputRef.current?.focus();
    inputRef.current?.select();
  }, []);

  // Reuse the file-browser leaf-name validation (no '/', control chars, etc.).
  const nameError = validateFolderName(name.trim());
  const nameValid = nameError === null;

  return (
    <Modal
      ariaLabel="Save results to my files"
      dismissible={!isBusy}
      onDismiss={onCancel}
      className="flex max-w-lg flex-col px-5 pb-4 pt-5"
    >
      <h2 className="text-md font-semibold text-text">Save results to my files</h2>
      <p className="mt-1 text-sm text-text-2">
        Saves the full result set as a CSV in your space. A <code>.csv</code> extension is added automatically.
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

      <p className="mt-4 mb-1 text-xs font-semibold uppercase tracking-wide text-text-3">Destination folder</p>
      <DestinationPicker
        bucket={bucket}
        items={[]}
        rootPrefix={rootPrefix}
        rootLabel={rootLabel}
        currentPrefix={rootPrefix}
        isBusy={isBusy}
        allowCurrentParent
        confirmDisabled={!nameValid}
        confirmLabel="Save here"
        busyLabel="Saving…"
        onConfirm={(destPrefix) => onSave({ destPrefix, filename: normalizeCsvName(name) })}
        onCancel={onCancel}
      />
    </Modal>
  );
}
