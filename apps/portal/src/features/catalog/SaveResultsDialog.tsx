import {useEffect, useRef, useState} from 'react';
import {Input} from '../../components/Input';
import {Modal} from '../../components/Modal';
import {DestinationPicker, validateFolderName} from '../file-browser';
import {SpaceSelect} from '../../components/SpaceSelect';
import {useFeature} from '../feature-flags';
import {normalizeResultsName, RESULTS_FORMATS} from './catalog.format';
import type {QuerySpace, ResultsFormat} from './catalog.types';
import {convertsFor, type SaveResultsInitial} from './useSaveResults';
import {FIELD_LABEL, SECTION_CAPTION} from '../../components/fieldStyles';
import {DIALOG_PANEL, DIALOG_TITLE} from '../../components/dialogChrome';

type Props = {
  /** The destination spaces the user can save into (personal first, then shared). */
  spaces: QuerySpace[];
  /** What the fields open with, read once at mount: the suggested name, or a cancelled overwrite's. */
  initial: SaveResultsInitial;
  isBusy?: boolean;
  /**
   * `destPrefix` is a full in-space key prefix (ends with "/"); `filename` is the leaf, normalized
   * to the chosen format's extension. `format` decides which path the hook takes — `csv` is the
   * synchronous copy, the rest go to the conversion plane.
   */
  onSave: (args: {destBucket: string; destPrefix: string; filename: string; format: ResultsFormat}) => void;
  onCancel: () => void;
  /**
   * The result columns this save would keep, in order, or null for all of them in the result's
   * own order. It decides the primary button's label through the same predicate the hook routes
   * on, so what the button says and what the save does cannot disagree.
   */
  columnIndexes: number[] | null;
};

// Derived from the map, not restated: a format added there but forgotten here would be silently
// missing from the select, which is the second source of truth `RESULTS_FORMATS` exists to remove.
// Insertion order for string keys is specified, so `csv` stays first and stays the default.
const FORMAT_ORDER = Object.keys(RESULTS_FORMATS) as ResultsFormat[];

/**
 * The space a restored destination sits in, found by bucket and root because the destination
 * carries no space id. Roots end in `/`, so `finance/` cannot claim a key under `finance2/`.
 */
function spaceHolding(spaces: QuerySpace[], destination: SaveResultsInitial['destination']): QuerySpace | undefined {
  if (!destination) return undefined;
  return spaces.find((s) => s.bucket === destination.bucket && destination.prefix.startsWith(s.rootPrefix));
}

/**
 * Destination-folder picker, a validated file-name field and a format choice, for saving a
 * result set into a space.
 *
 * CSV is the instant copy of the object Athena already wrote; Parquet, JSON and Excel are built
 * by the conversion plane and come back as a notification. The primary button says which of the
 * two is about to happen, so the wait is announced before the click rather than after it.
 *
 * When the user belongs to shared spaces, a space selector chooses which space to browse; the
 * picker remounts per space (keyed) so its breadcrumb/browse state resets cleanly. Save is
 * disabled until a destination is chosen and the name is valid.
 *
 * Reopened after a cancelled overwrite question, it starts from that question's name, format,
 * space and folder rather than its defaults, and the picker opens at that folder whenever that
 * space is the one selected.
 */
export function SaveResultsDialog({spaces, initial, isBusy = false, onSave, onCancel, columnIndexes}: Props) {
  const [name, setName] = useState(initial.name);
  const [format, setFormat] = useState<ResultsFormat>(initial.format);
  const restored = spaceHolding(spaces, initial.destination);
  const [spaceId, setSpaceId] = useState(restored?.id ?? spaces[0]?.id ?? '');
  const inputRef = useRef<HTMLInputElement>(null);
  // Off, the field is ABSENT rather than disabled, and the dialog is the one it was before this
  // spec: `format` stays 'csv' and the hook takes the copy path it always took.
  const canConvert = useFeature('resultsConversion');

  useEffect(() => {
    inputRef.current?.focus();
    inputRef.current?.select();
  }, []);

  const space = spaces.find((s) => s.id === spaceId) ?? spaces[0];

  // Reuse the file-browser leaf-name validation (no '/', control chars, etc.).
  const nameError = validateFolderName(name.trim());
  const nameValid = nameError === null;

  if (!space) return null;

  const isCopy = !convertsFor(format, columnIndexes);

  return (
    <Modal
      ariaLabel="Save results to my files"
      dismissible={!isBusy}
      onDismiss={onCancel}
      className={DIALOG_PANEL}>
      <h2 className={DIALOG_TITLE}>Save results</h2>
      <p className="mt-1 text-sm text-text-2">
        {columnIndexes !== null ? (
          <>
            Saves the result columns this grid is showing, in the order it shows them — a column worked out in your
            browser is not part of the results and is not saved. That is a file no straight copy can produce, so every
            format is converted first and arrives as a notification. The file extension is added automatically.
          </>
        ) : canConvert ? (
          <>
            Saves the full result set. <b>CSV</b> is saved straight away; the other formats are converted first and
            arrive as a notification. The file extension is added automatically.
          </>
        ) : (
          <>
            Saves the full result set as a CSV. A <code>.csv</code> extension is added automatically.
          </>
        )}
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

      {/* Not `SpaceSelect`: that one renders nothing below two options and carries a space's
          shared-ness in its option text. These four are always all four. */}
      {canConvert && (
        <div className="mt-3">
          <label
            htmlFor="save-results-format"
            className={FIELD_LABEL}>
            Format
          </label>
          <select
            id="save-results-format"
            value={format}
            disabled={isBusy}
            onChange={(e) => setFormat(e.target.value as ResultsFormat)}
            className="h-9 w-full rounded-md border border-border bg-surface px-3 text-base text-text focus-visible:border-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent disabled:opacity-45">
            {FORMAT_ORDER.map((key) => (
              <option
                key={key}
                value={key}>
                {RESULTS_FORMATS[key].label}
              </option>
            ))}
          </select>
        </div>
      )}

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

      {columnIndexes !== null && (
        <p className="mt-4 text-sm text-text-2">
          The file holds {columnIndexes.length} result {columnIndexes.length === 1 ? 'column' : 'columns'}, in the order
          shown.
        </p>
      )}

      <p className={`mt-4 mb-1 ${SECTION_CAPTION}`}>Destination folder</p>
      <DestinationPicker
        key={space.id}
        bucket={space.bucket}
        items={[]}
        rootPrefix={space.rootPrefix}
        rootLabel={space.rootLabel}
        currentPrefix={space.rootPrefix}
        startPrefix={space.id === restored?.id ? initial.destination?.prefix : undefined}
        isBusy={isBusy}
        allowCurrentParent
        confirmDisabled={!nameValid}
        confirmLabel={isCopy ? 'Save here' : 'Convert and save'}
        busyLabel="Saving…"
        onConfirm={(destPrefix) =>
          onSave({destBucket: space.bucket, destPrefix, filename: normalizeResultsName(name, format), format})
        }
        onCancel={onCancel}
      />
    </Modal>
  );
}
