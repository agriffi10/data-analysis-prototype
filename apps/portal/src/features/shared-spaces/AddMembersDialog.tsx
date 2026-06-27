import { useEffect, useId, useMemo, useRef, useState } from 'react';
import { Button } from '../../components/Button';
import { Modal } from '../../components/Modal';
import { parseMemberInput } from './memberInput';

type Props = {
  // In-flight while the add request is being enqueued — locks Add + dismiss.
  busy?: boolean;
  // Usernames already in the space (incl. the owner) — excluded from the result
  // so re-adding an existing member is a client-side no-op.
  existing: string[];
  onAdd: (members: string[]) => void;
  onCancel: () => void;
};

// SPEC-053 FR-002: add one or many members. A single textarea takes a single
// username or a bulk paste; we show how many valid, new usernames will be sent so
// the owner sees malformed/duplicate tokens silently drop before submitting.
export function AddMembersDialog({ busy = false, existing, onAdd, onCancel }: Props) {
  const [raw, setRaw] = useState('');
  const ref = useRef<HTMLTextAreaElement>(null);
  const helpId = useId();

  useEffect(() => {
    ref.current?.focus();
  }, []);

  const existingSet = useMemo(
    () => new Set(existing.map((m) => m.toLowerCase())),
    [existing],
  );
  // Valid, new (not already a member) usernames that will actually be sent.
  const members = useMemo(
    () => parseMemberInput(raw).filter((m) => !existingSet.has(m)),
    [raw, existingSet],
  );

  const attempt = () => {
    if (members.length > 0 && !busy) onAdd(members);
  };

  return (
    <Modal ariaLabel="Add members" onDismiss={onCancel} dismissible={!busy}>
      <div className="px-5 pb-4 pt-5">
        <h2 className="mb-3 text-md font-semibold text-text">Add members</h2>
        <p className="mb-3 text-sm text-text-2">
          Enter one or more usernames, separated by spaces, commas, or new lines.
          Unknown usernames are ignored. Members get access to the same shared
          files and tables.
        </p>
        <textarea
          ref={ref}
          rows={4}
          aria-label="Usernames"
          aria-describedby={helpId}
          disabled={busy}
          value={raw}
          placeholder="e.g. bob, cara"
          onChange={(e) => setRaw(e.target.value)}
          className="w-full rounded-md border border-border bg-surface px-3 py-2 font-mono text-base text-text placeholder:text-text-3 focus-visible:border-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent disabled:opacity-45"
        />
        <p id={helpId} className="mt-1.5 text-xs text-text-3">
          {members.length === 0
            ? 'No valid new usernames yet.'
            : `${members.length} username${members.length === 1 ? '' : 's'} to add: ${members.join(', ')}`}
        </p>
      </div>
      <div className="flex justify-end gap-2 rounded-b-lg border-t border-border bg-surface-2 px-5 py-4">
        <Button variant="ghost" onClick={onCancel} disabled={busy}>
          Cancel
        </Button>
        <Button
          variant="primary"
          onClick={attempt}
          disabled={members.length === 0 || busy}
        >
          {busy ? 'Adding…' : 'Add'}
        </Button>
      </div>
    </Modal>
  );
}
