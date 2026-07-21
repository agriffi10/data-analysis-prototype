import {useCallback, useEffect, useRef, useState} from 'react';
import {Modal} from '../../components/Modal';
import {DestinationPicker, prefixMarkerKey, type FileSpaceTarget} from '../file-browser';
import {splitLocation} from './dataQuality.format';
import type {DataQualitySpace} from './dataQuality.types';
import type {DataQualityTarget} from './useDataQualityCheck';

type Props = {
  /**
   * From `usableSpaceTargets` (SPEC-057) — personal first, then usable shared A–Z.
   * Empty renders null (see below).
   */
  spaces: FileSpaceTarget[];
  isPending?: boolean;
  onStart: (target: DataQualityTarget) => void;
  onCancel: () => void;
};

/**
 * The dashboard's entry point into a quality check: pick a space, browse to a folder
 * (or one file), start.
 *
 * It is the `SaveResultsDialog` composition — `Modal` + a space `<select>` + a keyed
 * `DestinationPicker` — with the filename field removed and the picker put into SPEC-124's
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
  // The marker owner is the space's root segment: `{space}/DO_NOT_DELETE.txt`.
  const markerKey = prefixMarkerKey(space.label);

  const handleConfirm = (destPrefix: string, _destBucket: string, selectedFileKey?: string) => {
    const dqSpace: DataQualitySpace = {
      kind: space.kind,
      bucket: space.bucket,
      // The SPACE is identified to the control plane by its root prefix, never by the
      // folder being browsed (SPEC-109).
      prefix: space.rootPrefix
    };
    onStart({space: dqSpace, location: selectedFileKey ?? destPrefix});
  };

  return (
    <Modal
      ariaLabel="Start a quality check"
      dismissible={!isPending}
      onDismiss={onCancel}
      className="flex max-w-lg flex-col px-5 pb-4 pt-5">
      <h2 className="text-md font-semibold text-text">New quality check</h2>
      <p className="mt-1 text-sm text-text-2">
        Choose a folder to check, or a single file. This <strong className="font-semibold text-text">only reads</strong>{' '}
        your data — nothing is modified, moved, or deleted. The check runs in the background and can take a few minutes;
        you’ll get a notification when it finishes.
      </p>

      {spaces.length > 1 && (
        <div className="mt-3">
          <label
            htmlFor="dq-start-space"
            className="mb-1.5 block text-sm font-medium text-text">
            Space
          </label>
          <select
            ref={selectRef}
            id="dq-start-space"
            value={space.id}
            disabled={isPending}
            onChange={(e) => setSpaceId(e.target.value)}
            className="h-9 w-full rounded-md border border-border bg-surface px-3 text-base text-text focus-visible:border-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent disabled:opacity-45">
            {spaces.map((s) => (
              <option
                key={s.id}
                value={s.id}>
                {s.label}
                {s.kind === 'shared' ? ' (shared)' : ''}
              </option>
            ))}
          </select>
        </div>
      )}

      <div className="mt-4 flex items-baseline justify-between gap-3">
        <p className="flex-none text-xs font-semibold uppercase tracking-wide text-text-3">Data to check</p>
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
        // Without this, `currentParentBlocked` disables confirm AT THE SPACE ROOT and the
        // root target is dead on arrival.
        allowCurrentParent
        selectableFiles
        markerKey={markerKey}
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
