import {useCallback, useEffect, useRef, useState} from 'react';
import {Modal} from '../../components/Modal';
import {DestinationPicker, type FileSpaceTarget} from '../file-browser';
import {SpaceSelect} from '../../components/SpaceSelect';
import {splitLocation} from './dataQuality.format';
import type {DataQualitySpace} from './dataQuality.types';
import type {DataQualityTarget} from './useDataQualityCheck';
import {SECTION_CAPTION} from '../../components/fieldStyles';
import {DIALOG_PANEL, DIALOG_TITLE} from '../../components/dialogChrome';

type Props = {
  /**
   * From `usableSpaceTargets` — personal first, then usable shared A–Z.
   * Empty renders null (see below).
   */
  spaces: FileSpaceTarget[];
  isPending?: boolean;
  onStart: (target: DataQualityTarget) => void;
  onCancel: () => void;
};

/**
 * Why a check cannot be run on the space root, shown on the picker's disabled confirm.
 *
 * **The space root is not a data folder.** A check builds an external table over the folder it
 * is given, and Athena reads a table's location recursively, so a check at the top of a space
 * counts the portal's own bookkeeping — the query-results folder, archive receipts, shared-table
 * copies — as the user's data. It succeeds and reports the wrong numbers, which is why the
 * server refuses it (`location_is_space_root`) rather than qualifying the report.
 *
 * Wording, not a predicate: the picker already knows when the user is standing at the root, and
 * a second copy of that comparison here would be free to drift from it. The server's refusal is
 * the real gate; this sentence exists so a user never reaches it.
 */
export const CHECK_AT_ROOT_REFUSAL =
  'A check reads every file in the folder you give it, so it can’t be run here — the top of a space also ' +
  'holds your query results, archived copies and shared tables, and they’d be counted as your data. Open the ' +
  'folder holding the files you want checked, or pick a single file.';

/**
 * The dashboard's entry point into a quality check: pick a space, browse to a folder
 * (or one file), start.
 *
 * It is the `SaveResultsDialog` composition — `Modal` + a space `<select>` + a keyed
 * `DestinationPicker` — with the filename field removed and the picker put into the dialog's
 * `selectableFiles` mode, because a check can target a single file where a save never can.
 *
 * The picker owns the browse state; this dialog is TOLD the target via `onTargetChange` and
 * uses it for two things the picker can't produce on its own: the target line and a confirm
 * label that names what is about to be checked. Never a generic "OK" — the user is one click
 * from a background job.
 *
 * Enqueueing is NOT done here. The Files-browser action and this one both go through
 * `useDataQualityCheck`; a second enqueue path is exactly what this dialog must not become.
 */
export function StartQualityCheckDialog({spaces, isPending = false, onStart, onCancel}: Props) {
  const [spaceId, setSpaceId] = useState(spaces[0]?.id ?? '');
  const [target, setTarget] = useState<{prefix: string; fileKey?: string} | null>(null);
  const selectRef = useRef<HTMLSelectElement>(null);

  const space = spaces.find((s) => s.id === spaceId) ?? spaces[0];

  // `Modal` sets `initialFocus: false` and defers to the consumer. There is no text field
  // here to inherit it (SaveResultsDialog focuses its filename input), so focus goes to the
  // space selector; with one space there is no selector and the trap's fallback lands focus
  // on the panel itself.
  useEffect(() => {
    selectRef.current?.focus();
  }, []);

  // Stable, or the picker's report-the-target effect would re-fire every render.
  const handleTargetChange = useCallback((next: {prefix: string; fileKey?: string}) => {
    setTarget(next);
  }, []);

  // Zero usable spaces means the space bucket env var is unset (a personal space always
  // exists), which is a configuration error, not an empty list. The page keeps the action
  // hidden in that case; rendering null here is the belt to that braces.
  if (!space) return null;

  const location = target?.fileKey ?? target?.prefix ?? space.rootPrefix;
  const targetParts = splitLocation(location);
  const isFile = target?.fileKey !== undefined;
  const handleConfirm = (destPrefix: string, _destBucket: string, selectedFileKey?: string) => {
    const dqSpace: DataQualitySpace = {
      kind: space.kind,
      bucket: space.bucket,
      // The SPACE is identified to the control plane by its root prefix, never by the
      // folder being browsed.
      prefix: space.rootPrefix
    };
    onStart({space: dqSpace, location: selectedFileKey ?? destPrefix});
  };

  return (
    <Modal
      ariaLabel="Start a quality check"
      dismissible={!isPending}
      onDismiss={onCancel}
      className={DIALOG_PANEL}>
      <h2 className={DIALOG_TITLE}>New quality check</h2>
      <p className="mt-1 text-sm text-text-2">
        Choose a folder to check, or a single file. This <strong className="font-semibold text-text">only reads</strong>{' '}
        your data — nothing is modified, moved, or deleted. The check runs in the background and can take a few minutes;
        you’ll get a notification when it finishes.
      </p>

      <SpaceSelect
        ref={selectRef}
        id="dq-start-space"
        label="Space"
        spaces={spaces}
        value={space.id}
        disabled={isPending}
        onChange={setSpaceId}
      />

      <div className="mt-4 flex items-baseline justify-between gap-3">
        <p className={`flex-none ${SECTION_CAPTION}`}>Data to check</p>
        {/* The head is what gets truncated, because the END of a location is what identifies
            it. Same split-span construction as `DataQualityRunRow` (and the same reason for
            NOT using `direction: rtl`: under bidi a trailing "/" in an S3 key is neutral
            punctuation and moves to the wrong end). */}
        <p
          id="dq-start-target"
          className="flex min-w-0 flex-1 items-baseline justify-end font-mono text-xs text-text-2">
          <span className="truncate text-text-3">{targetParts.parent}</span>
          <span className="flex-none text-text">{targetParts.name}</span>
        </p>
      </div>

      <DestinationPicker
        // Remounting per space resets the breadcrumb, the browse prefix, and any file
        // selection to that space's root — a target can never straddle two spaces.
        key={space.id}
        bucket={space.bucket}
        items={[]}
        rootPrefix={space.rootPrefix}
        rootLabel={space.label}
        currentPrefix={space.rootPrefix}
        // The space root is refused, so `allowCurrentParent` stays OFF and the picker
        // disables confirm while the user is standing at it. A file selected at the root is
        // still confirmable — the picker exempts a selected file, and the server allows it.
        currentParentMessage={CHECK_AT_ROOT_REFUSAL}
        selectableFiles
        listLabel="Folders and files to check"
        onTargetChange={handleTargetChange}
        isBusy={isPending}
        confirmLabel={isFile ? 'Check this file' : 'Check this folder'}
        busyLabel="Starting…"
        onConfirm={handleConfirm}
        onCancel={onCancel}
      />
    </Modal>
  );
}
