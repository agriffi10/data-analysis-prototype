import {useRef, useState} from 'react';
import {ConfirmDialog} from '../../components/ConfirmDialog';
import {FormDialog} from '../../components/FormDialog';
import {Input} from '../../components/Input';
import {OperationOutcomeBanner} from './OperationSummaryBanner';
import {validateFolderNameForPlane} from './fileBrowser.service';
import {conflictKind} from './fileOps.request';
import type {FileOpConflicts} from './useFileOpConflicts';

/** What the user chose to do about the items that could not be placed. */
export type ConflictResolution = {onConflict: 'refuse' | 'overwrite'; targetName?: string};

type Props = {
  conflicts: FileOpConflicts;
  busy: boolean;
  onResolve: (choice: ConflictResolution) => void;
  onClose: () => void;
};

/**
 * What a run could not place, and the two ways out of it.
 *
 * **Overwrite is the destructive one and it says so in words.** Versioning is off on both
 * buckets, so an overwritten object is gone — there is no version history to walk back to and no
 * trash. That sentence reaches the user; a reason code would not.
 *
 * **"Or type a new name" survives, and it is what most people mean.** A rename is the one shape
 * where a single item carries a name the user chose, so a different name re-submits with
 * `onConflict: 'refuse'` — strictly safer, and it destroys nothing. It is offered only for that
 * shape: over a multi-item move there is no one name to type.
 *
 * **Only the conflicted items are re-sent.** The rest of the run already happened; re-sending
 * them would copy them a second time.
 */
export function FileOpConflictsDialog({conflicts, busy, onResolve, onClose}: Props) {
  const [confirmingOverwrite, setConfirmingOverwrite] = useState(false);
  const [renaming, setRenaming] = useState(false);
  const {payload, results} = conflicts;
  // The rename shape: one item, carrying the name the user typed. `targetName` is the only
  // source for it — the plane sends it back precisely so this can be offered.
  const renameTarget = results.length === 1 ? payload.conflicts?.[0]?.targetName : undefined;
  // A renamed FOLDER lands in the destination, so its new name is checked there before it is re-sent.
  const renamed = payload.conflicts?.[0];
  const renameParent = renamed && conflictKind(renamed) === 'folder' ? payload.destination?.prefix : undefined;

  if (confirmingOverwrite) {
    return (
      <ConfirmDialog
        title={`Overwrite ${results.length === 1 ? 'this item' : `these ${results.length} items`}?`}
        ariaLabel="Confirm overwrite"
        confirmLabel="Overwrite"
        busyLabel="Submitting…"
        busy={busy}
        confirmVariant="danger"
        tone="danger"
        onConfirm={() => onResolve({onConflict: 'overwrite'})}
        onCancel={() => setConfirmingOverwrite(false)}>
        {/* Not `irreversible`, whose standard line is "This can't be undone." — true, and far too
            mild for what this does. There is no version history and no trash on these buckets, so
            the thing already at the destination is simply gone. */}
        <p className="mt-2 text-sm text-text-2">
          Whatever is already at the destination will be replaced. There is no version history and no trash here, so the
          replaced files <b>cannot be recovered</b>.
        </p>
        <p className="mt-2 text-sm text-text-2">
          Anything created at the destination since you first asked is left alone — Data Quarry only overwrites what was
          already there.
        </p>
      </ConfirmDialog>
    );
  }

  if (renaming && renameTarget !== undefined) {
    return (
      <RenameAwayDialog
        current={renameTarget}
        parentPrefix={renameParent}
        busy={busy}
        onSubmit={onResolve}
        onCancel={() => setRenaming(false)}
      />
    );
  }

  return (
    <ConfirmDialog
      title="Some items could not be placed"
      ariaLabel="Review conflicts"
      confirmLabel={renameTarget === undefined ? 'Overwrite…' : 'Use a different name…'}
      cancelLabel="Close"
      busy={busy}
      onConfirm={() => (renameTarget === undefined ? setConfirmingOverwrite(true) : setRenaming(true))}
      onCancel={onClose}>
      <p className="mt-2 text-sm text-text-2">
        Something was already in the way, so Data Quarry left it alone. Everything else in that request went ahead.
      </p>
      <OperationOutcomeBanner
        title={`${results.length} ${results.length === 1 ? 'item needs' : 'items need'} your attention`}
        results={results}
        className="mt-3"
      />
      {payload.more && (
        <p className="mt-2 text-sm text-text-3">
          This list was shortened. Resolving these will leave any others to be requested again.
        </p>
      )}
      {renameTarget !== undefined && (
        <p className="mt-3 text-sm text-text-2">
          You can also{' '}
          <button
            type="button"
            className="underline underline-offset-2 hover:text-accent-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
            onClick={() => setConfirmingOverwrite(true)}>
            overwrite what is there
          </button>
          , which cannot be undone.
        </p>
      )}
    </ConfirmDialog>
  );
}

/**
 * "Or type a new name" — the safer half of a rename's conflict.
 *
 * Its own dialog rather than a branch in the body above, for the reason the same-folder copy's
 * is: the two have nothing in common below the title, and this one IS a name prompt, so it takes
 * the shared name-a-thing chrome and its single Enter-submitting field.
 */
function RenameAwayDialog({
  current,
  parentPrefix,
  busy,
  onSubmit,
  onCancel
}: {
  current: string;
  /** Where a renamed folder lands; absent for a file, which the parent-dependent rules skip. */
  parentPrefix?: string;
  busy: boolean;
  onSubmit: (choice: ConflictResolution) => void;
  onCancel: () => void;
}) {
  const [name, setName] = useState(current);
  const inputRef = useRef<HTMLInputElement>(null);
  const validationError = validateFolderNameForPlane(name, parentPrefix);

  return (
    <FormDialog
      title="Use a different name"
      ariaLabel="Rename to avoid the conflict"
      submitLabel="Request again"
      busy={busy}
      busyLabel="Submitting…"
      submitDisabled={validationError !== null || name.trim() === current}
      autoFocusRef={inputRef}
      autoFocusSelect
      className="max-w-lg"
      onSubmit={() => onSubmit({onConflict: 'refuse', targetName: name.trim()})}
      onCancel={onCancel}>
      <p className="mt-2 text-sm text-text-2">Nothing is overwritten — the new name has to be free.</p>
      <div className="mt-3">
        <Input
          id="conflict-rename-input"
          ref={inputRef}
          label="New name"
          value={name}
          onChange={(e) => setName(e.target.value)}
          error={validationError ?? undefined}
        />
      </div>
    </FormDialog>
  );
}
