import {useMemo, useRef, useState} from 'react';
import {FormDialog} from '../../components/FormDialog';
import {Input} from '../../components/Input';
import {Banner} from '../../components/Banner';
import {PartitionKeysField} from './PartitionKeysField';
import {buildPartitionKeys, type DraftPartitionKey} from './partitionKeys';
import {isValidTableName, suggestTableName} from './tableBuild.service';
import {CATALOG_IDENTIFIER_RULE} from '../../lib/catalogIdentifier';
import type {PartitionKey} from './tableBuild.types';

type Props = {
  // The folder being turned into a table — drives the suggested name + the copy.
  folderName: string;
  // The full key of that folder within its space, shown read-only so the user can see
  // exactly which folder they're naming a table for. Empty = the space root.
  folderPath?: string;
  // In-flight while the request is being enqueued — locks the form + dismissal.
  busy?: boolean;
  // A send failure to surface inline (the dialog stays open so the user can retry).
  submitError?: string | null;
  onSubmit: (args: {tableName: string; partitionKeys: PartitionKey[]}) => void;
  onCancel: () => void;
};

// SPEC-071 FR-002: the "Create table from this folder" prompt — a catalog-safe name
// (pre-filled from the folder name) plus an optional partition-keys section. Confirm
// stays disabled until the name AND every declared key are valid; the server
// re-validates authoritatively (SPEC-067), so this is UX only. Composes the shared
// Modal/Input/Button primitives.
export function CreateTableDialog({folderName, folderPath, busy = false, submitError, onSubmit, onCancel}: Props) {
  const [name, setName] = useState(() => suggestTableName(folderName));
  const [touched, setTouched] = useState(false);
  const [keys, setKeys] = useState<DraftPartitionKey[]>([]);
  const inputRef = useRef<HTMLInputElement>(null);

  const trimmed = name.trim();
  const nameValid = isValidTableName(trimmed);
  const nameError = touched && !nameValid && trimmed.length > 0 ? CATALOG_IDENTIFIER_RULE : undefined;

  const partition = useMemo(() => buildPartitionKeys(keys), [keys]);
  const canSubmit = nameValid && partition.valid && !busy;

  const attempt = () => {
    if (canSubmit) onSubmit({tableName: trimmed, partitionKeys: partition.keys});
  };

  return (
    <FormDialog
      title="Create table from this folder"
      ariaLabel="Create table from this folder"
      submitLabel="Create table"
      busy={busy}
      busyLabel="Submitting…"
      submitDisabled={!canSubmit}
      autoFocusRef={inputRef}
      autoFocusSelect
      className="max-w-lg"
      scrollBody
      onSubmit={attempt}
      onCancel={onCancel}>
      {/* `mt-1` reproduces the gap the old markup got from an `mb-1` on the heading. */}
      <p className="mb-3 mt-1 text-sm text-text-2">
        Creates a queryable table over the files in this folder. It’s built in the background — you’ll be notified when
        it’s ready or if it couldn’t be created.
      </p>

      {folderPath !== undefined && (
        <div className="mb-4">
          <span className="text-xs font-medium uppercase tracking-wide text-text-2">Folder</span>
          <p
            className="mt-0.5 break-all rounded-md border border-border bg-surface-2 px-2.5 py-1.5 font-mono text-sm text-text"
            title={folderPath || '/'}>
            {folderPath || '/ (space root)'}
          </p>
        </div>
      )}

      <Input
        ref={inputRef}
        id="create-table-name"
        label="Table name"
        required
        aria-required="true"
        value={name}
        placeholder="e.g. sales_2026"
        error={nameError}
        disabled={busy}
        onChange={(e) => {
          setTouched(true);
          setName(e.target.value);
        }}
      />

      <PartitionKeysField
        value={keys}
        errors={partition.errors}
        disabled={busy}
        onChange={setKeys}
      />

      {submitError && (
        <Banner
          variant="danger"
          className="mt-4"
          role="alert">
          {submitError}
        </Banner>
      )}
    </FormDialog>
  );
}
