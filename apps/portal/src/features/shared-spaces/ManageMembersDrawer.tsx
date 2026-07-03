import {useState} from 'react';
import {Drawer} from '../../components/Drawer';
import {Button} from '../../components/Button';
import {Banner} from '../../components/Banner';
import {ConfirmDialog} from '../../components/ConfirmDialog';
import {cx} from '../../lib/cx';
import {AddMembersDialog} from './AddMembersDialog';
import {RefreshConnectionsButton} from './RefreshConnectionsButton';
import type {Member} from './sharedSpaces.types';

type Props = {
  open: boolean;
  onClose: () => void;
  space: string;
  owner: string;
  /** Current membership (the owner-readable cache projection), with join status; includes the owner. */
  members: Member[];
  /** True if the member projection isn't available yet (older cache entry) — shows a note instead of an empty list. */
  unavailable?: boolean;
  busy?: boolean;
  /** Re-read member state on demand (a Pending → Active flip lands async, after the member acks). */
  onRefresh: () => void;
  refreshing?: boolean;
  onAddMembers: (members: string[]) => void;
  onRemoveMembers: (members: string[]) => void;
};

/**
 * Owner-only Manage-members drawer: lists current members (owner marked, never
 * removable) with Add + per-member Remove. All changes are async pipeline requests
 * (the parent enqueues via `useManageMembers`) that apply after a
 * Refresh-connections — the inline note sets that expectation.
 */
export function ManageMembersDrawer({
  open,
  onClose,
  space,
  owner,
  members,
  unavailable = false,
  busy = false,
  onRefresh,
  refreshing = false,
  onAddMembers,
  onRemoveMembers
}: Props) {
  const [addOpen, setAddOpen] = useState(false);
  const [removing, setRemoving] = useState<string | null>(null);

  // Owner first, then the rest A–Z; the owner can't be removed here.
  const others = members.filter((m) => m.username !== owner).sort((a, b) => a.username.localeCompare(b.username));

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
      title={space}
      titleClassName="font-mono"
      subtitle="Members · everyone shares the same files and tables"
      ariaLabel="Manage members"
      closeLabel="Close manage members"
      headerAccessory={
        <div className="ml-2 flex flex-none items-center gap-1.5">
          <RefreshConnectionsButton
            refreshing={refreshing}
            onRefresh={onRefresh}
          />
          <Button
            variant="primary"
            size="sm"
            onClick={() => setAddOpen(true)}
            disabled={busy}>
            Add members
          </Button>
        </div>
      }
      // While a nested dialog is open it owns Escape.
      closeOnEscape={!addOpen && !removing}>
      {unavailable && (
        <Banner variant="info">
          Member details aren&apos;t available yet — add or remove a member, then Refresh connections to load the list.
        </Banner>
      )}

      <ul
        role="list"
        className="divide-y divide-border rounded-lg border border-border">
        <li className="flex items-center gap-3 px-4 py-2.5">
          <Avatar name={owner} />
          <span className="min-w-0 truncate font-medium text-text">{owner}</span>
          <span className="flex-none rounded-full border border-border bg-surface px-2.5 py-0.5 text-xs font-medium text-text-2">
            Owner
          </span>
          <div className="flex-1" />
        </li>
        {others.map((member) => (
          <li
            key={member.username}
            className="flex items-center gap-3 px-4 py-2.5">
            <Avatar name={member.username} />
            <span className="min-w-0 truncate font-medium text-text">{member.username}</span>
            <MemberStatusBadge status={member.status} />
            <div className="flex-1" />
            <Button
              variant="ghost"
              size="sm"
              className="text-danger hover:bg-danger-soft hover:text-danger"
              onClick={() => setRemoving(member.username)}
              disabled={busy}>
              Remove
            </Button>
          </li>
        ))}
      </ul>

      <p className="text-xs text-text-3">
        A <span className="font-medium text-text-2">Pending</span> member has been invited but hasn&apos;t signed in
        yet; they become <span className="font-medium text-text-2">Active</span> once they do. Use Refresh to check for
        updates.
      </p>

      {addOpen && (
        <AddMembersDialog
          busy={busy}
          existing={members.map((m) => m.username)}
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
          onCancel={() => setRemoving(null)}>
          <p>
            Remove <span className="font-mono">{removing}</span> from <span className="font-mono">{space}</span>? They
            lose access to its files and tables. The shared data isn&apos;t deleted.
          </p>
        </ConfirmDialog>
      )}
    </Drawer>
  );
}

// Per-member join status as a colored dot + text label (SPEC-073). Like the
// Connections-page StatusBadge, the text label always carries the meaning, so the
// color/dot is never the only signal (WCAG AA).
function MemberStatusBadge({status}: {status: Member['status']}) {
  const active = status === 'active';
  return (
    <span
      className={cx(
        'inline-flex flex-none items-center gap-1.5 rounded-full px-2 py-0.5 text-xs font-semibold',
        active ? 'bg-success-soft text-success' : 'bg-warning-soft text-warning'
      )}>
      <span className="h-[7px] w-[7px] rounded-full bg-current" />
      {active ? 'Active' : 'Pending'}
    </span>
  );
}

// Circular avatar showing the first two letters of the username. Decorative — the
// username text beside it carries the name.
function Avatar({name}: {name: string}) {
  return (
    <span
      aria-hidden="true"
      className="grid h-7 w-7 flex-none place-items-center rounded-full bg-gradient-to-br from-accent to-accent-hover text-xs font-semibold text-white">
      {name.slice(0, 2).toUpperCase()}
    </span>
  );
}
