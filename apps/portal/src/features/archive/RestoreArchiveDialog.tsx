import {useRef, useState} from 'react';
import {FormDialog} from '../../components/FormDialog';
import {Input} from '../../components/Input';
import {isArchiveId} from './useArchive';

type Props = {
  /** Where the restore will land — the space the user is browsing, named in the dialog. */
  spaceLabel: string;
  busy?: boolean;
  /** An enqueue failure to surface inline; the dialog stays open so the id is not retyped. */
  submitError?: string | null;
  onSubmit: (archiveId: string) => void;
  onCancel: () => void;
};

/**
 * The Restore Archived Data modal (SPEC-172 FR-003).
 *
 * One field, and therefore the single-field case `submitOnEnterRef` exists for — **the opposite
 * call from `ArchiveDialog`, for the opposite reason**: Enter here submits an id the user has
 * just finished typing, where Enter there would delete a folder.
 *
 * **The id is validated as a UUID before enqueue, and that is not the boundary.** The control
 * plane checks it again before building any key (SPEC-170 FR-002). This copy exists so a typo
 * costs a sentence now instead of a notification later — which on this plane is the whole
 * difference, since a request that reaches the machine and fails still had to be read by someone
 * hours after they stopped thinking about it.
 *
 * **It restores into the space the user is browsing, and says which one.** The space comes from
 * the route (SPEC-113's rule, SPEC-170 FR-001), never from the archive — an archive belonging to
 * another space is then simply not found, rather than an oracle for what exists elsewhere.
 */
export function RestoreArchiveDialog({spaceLabel, busy = false, submitError, onSubmit, onCancel}: Props) {
  const [value, setValue] = useState('');
  const [attempted, setAttempted] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const trimmed = value.trim();
  const valid = isArchiveId(trimmed);
  // Shown on submit, never as you type: an id is invalid for every keystroke but the last, and a
  // field that turns red on the first character is a field that is wrong about the user.
  const error =
    attempted && !valid
      ? 'That doesn’t look like an archive id. Ids look like 3f8a1c2e-9b4d-4a17-8c65-2e0d7b1f4a93.'
      : null;

  return (
    <FormDialog
      title="Restore archived data"
      ariaLabel="Restore archived data"
      submitLabel="Restore"
      busyLabel="Starting…"
      busy={busy}
      autoFocusRef={inputRef}
      onSubmit={() => {
        setAttempted(true);
        // Validation happens on submit rather than through `submitDisabled`: a disabled control
        // is not a refusal, and the user needs to be told what a valid id looks like (SPEC-175's
        // recorded rule — `submitDisabled` never stands in for an explanation).
        if (isArchiveId(trimmed)) onSubmit(trimmed);
      }}
      onCancel={onCancel}>
      <p className="mt-3 text-sm text-text-2">
        Everything in the archive is restored to <span className="font-medium text-text">{spaceLabel}</span>, back where
        it came from.
      </p>

      <div className="mt-4">
        <Input
          ref={inputRef}
          label="Archive id"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          error={error}
          placeholder="3f8a1c2e-9b4d-4a17-8c65-2e0d7b1f4a93"
          autoComplete="off"
          spellCheck={false}
        />
      </div>

      <p className="mt-2 text-xs text-text-3">
        You’ll find the id in your <span className="font-medium">archive</span> folder — each archive has a folder named
        after its id, holding a receipt you can download.
      </p>

      <p className="mt-4 text-sm text-text-2">
        Restoring takes <strong>several hours</strong>, because archived files are kept in long-term storage. You’ll get
        a notification when it starts and another when it finishes.
      </p>

      {submitError && (
        <p
          role="alert"
          className="mt-3 rounded-md border border-danger-soft bg-danger-soft p-3 text-sm text-danger">
          {submitError}
        </p>
      )}
    </FormDialog>
  );
}
