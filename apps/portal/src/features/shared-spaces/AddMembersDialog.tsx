import {useId, useMemo, useState} from 'react';
import {FormDialog} from '../../components/FormDialog';
import {UsernameChipsField} from '../user-directory/UsernameChipsField';
import {useUsernameSuggestions} from '../user-directory/useUsernameSuggestions';

type Props = {
  /** In-flight while the add request is being enqueued — locks Add + dismiss. */
  busy?: boolean;
  /**
   * Usernames already in the space (incl. the owner) — excluded from the result so
   * re-adding an existing member is a client-side no-op.
   */
  existing: string[];
  onAdd: (members: string[]) => void;
  onCancel: () => void;
};

/**
 * Add one or many members, choosing from existing usernames rather than remembering them.
 *
 * The field suggests names from the published directory (SPEC-146/147) and commits them as
 * chips, but it **never blocks a name the directory does not know** — the directory is up to a
 * day stale and is not the authority on who exists. An unrecognised name is reported back by
 * notification, which is what the copy below now says: it previously claimed such names were
 * "ignored", which had been untrue since `add_members.py` started notifying the owner.
 */
export function AddMembersDialog({busy = false, existing, onAdd, onCancel}: Props) {
  const [members, setMembers] = useState<string[]>([]);
  const helpId = useId();
  const suggestions = useUsernameSuggestions();

  // The drawer populates `existing` with every member INCLUDING the owner, and this dialog is
  // owner-only, so passing it straight through as `exclude` is a like-for-like translation of
  // the filter the textarea version applied — not a new restriction. It is deliberately NOT the
  // pipeline's `normalize_members`, which drops the owner for its own reasons and is not what
  // this relies on.
  const existingSet = useMemo(() => new Set(existing.map((m) => m.toLowerCase())), [existing]);

  const attempt = () => {
    if (members.length > 0 && !busy) onAdd(members);
  };

  return (
    // No `autoFocusRef`: the chips field focuses itself, and Enter inside its combobox
    // commits a chip (it `preventDefault`s), so the form's submit never fires from it.
    <FormDialog
      title="Add members"
      ariaLabel="Add members"
      submitLabel="Add"
      busy={busy}
      busyLabel="Adding…"
      submitDisabled={members.length === 0}
      onSubmit={attempt}
      onCancel={onCancel}>
      {/* `mt-3` reproduces the gap the old markup got from an `mb-3` on the heading. */}
      <p className="mb-3 mt-3 text-sm text-text-2">
        Start typing a username to see suggestions, or enter several separated by spaces, commas, or new lines. A name
        that isn&rsquo;t recognised is reported back to you as a notification. Members get access to the same shared
        files and tables.
      </p>
      <UsernameChipsField
        {...suggestions}
        label="Usernames"
        listLabel="Members to add"
        value={members}
        onChange={setMembers}
        exclude={existingSet}
        excludeReason={(name) => `${name} is already a member of this space.`}
        disabled={busy}
        placeholder="e.g. bob, cara"
        describedBy={helpId}
        autoFocus
      />
      <p
        id={helpId}
        className="mt-1.5 text-xs text-text-3">
        {members.length === 0
          ? // This exact sentence is what tells a user their input did not take. Pinned by a
            // test; do not reword it.
            'No valid new usernames yet.'
          : // The names themselves are no longer repeated here — the chips above carry them,
            // and reading the same list twice is noise.
            `${members.length} username${members.length === 1 ? '' : 's'} to add.`}
      </p>
    </FormDialog>
  );
}
