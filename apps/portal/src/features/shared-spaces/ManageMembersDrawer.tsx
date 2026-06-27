import { useState } from 'react';
import { Drawer } from '../../components/Drawer';
import { Button } from '../../components/Button';
import { Banner } from '../../components/Banner';
import { ConfirmDialog } from '../../components/ConfirmDialog';
import { AddMembersDialog } from './AddMembersDialog';

type Props = {
  open: boolean;
  onClose: () => void;
  // The space being managed and its current membership (the owner-readable
  // projection from the cache, SPEC-053). `members` includes the owner.
  space: string;
  owner: string;
  members: string[];
  // True if the member projection isn't available yet (e.g. an older cache entry
  // written before SPEC-053) — show a friendly note instead of an empty list.
  unavailable?: boolean;
  busy?: boolean;
  onAddMembers: (members: string[]) => void;
  onRemoveMembers: (members: string[]) => void;
};

// SPEC-053 FR-001: owner-only Manage-members drawer (SPEC-036 `Drawer`). Lists the
// current members (owner marked, never removable) with Add + per-member Remove.
// All changes are pipeline requests (the parent enqueues via `useManageMembers`)
// that apply after a Refresh-connections (SPEC-052) — the inline note sets that
// expectation since the effect is asynchronous.
export function ManageMembersDrawer({
  open,
  onClose,
  space,
  owner,
  members,
  unavailable = false,
  busy = false,
  onAddMembers,
  onRemoveMembers,
}: Props) {
  const [addOpen, setAddOpen] = useState(false);
  const [removing, setRemoving] = useState<string | null>(null);

  // Owner first, then the rest A–Z; the owner is implicitly a member and can't be
  // removed here (ownership changes via delete, SPEC-054).
  const others = members
    .filter((m) => m !== owner)
    .sort((a, b) => a.localeCompare(b));

  const handleAdd = (toAdd: string[]) => {
    setAddOpen(false);
    onAddMembers(toAdd);
  };

  const confirmRemove = () => {
    if (!removing) return;
    const target = removing;
    setRemoving(null);
    onRemoveMembers([target]);
  };

  return (
    <Drawer
      open={open}
      onClose={onClose}
      title="Manage members"
      headerAccessory={
        <span className="truncate font-mono text-sm text-text-3">{space}</span>
      }
      // While a nested dialog is open it owns Escape (SPEC-036 pattern).
      closeOnEscape={!addOpen && !removing}
    >
      <div className="flex items-center justify-between gap-2">
        <p className="text-sm text-text-2">
          {others.length === 0
            ? 'Just you so far.'
            : `${others.length + 1} members`}
        </p>
        <Button variant="primary" onClick={() => setAddOpen(true)} disabled={busy}>
          Add members
        </Button>
      </div>

      {unavailable && (
        <Banner variant="info">
          Member details aren&apos;t available yet — add or remove a member, then
          Refresh connections to load the list.
        </Banner>
      )}

      <ul role="list" className="divide-y divide-border rounded-lg border border-border">
        <li className="flex items-center justify-between gap-3 px-4 py-2.5">
          <span className="min-w-0 truncate font-mono text-sm text-text">
            {owner}
          </span>
          <span className="flex-none rounded-full border border-border bg-surface px-2.5 py-0.5 text-xs font-medium text-text-2">
            Owner
          </span>
        </li>
        {others.map((member) => (
          <li
            key={member}
            className="flex items-center justify-between gap-3 px-4 py-2.5"
          >
            <span className="min-w-0 truncate font-mono text-sm text-text">
              {member}
            </span>
            <Button
              variant="ghost"
              onClick={() => setRemoving(member)}
              disabled={busy}
            >
              Remove
            </Button>
          </li>
        ))}
      </ul>

      <p className="text-xs text-text-3">
        Changes apply after the member&apos;s next sign-in; use Refresh
        connections to see the updated list.
      </p>

      {addOpen && (
        <AddMembersDialog
          busy={busy}
          existing={members}
          onAdd={handleAdd}
          onCancel={() => setAddOpen(false)}
        />
      )}
      {removing && (
        <ConfirmDialog
          title="Remove member"
          ariaLabel={`Remove ${removing}`}
          tone="danger"
          confirmVariant="danger"
          confirmLabel="Remove"
          busy={busy}
          busyLabel="Removing…"
          onConfirm={confirmRemove}
          onCancel={() => setRemoving(null)}
        >
          <p>
            Remove <span className="font-mono">{removing}</span> from{' '}
            <span className="font-mono">{space}</span>? They lose access to its
            files and tables. The shared data isn&apos;t deleted.
          </p>
        </ConfirmDialog>
      )}
    </Drawer>
  );
}
