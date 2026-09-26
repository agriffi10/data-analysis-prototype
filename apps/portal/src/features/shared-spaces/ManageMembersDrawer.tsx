import {useState} from 'react';
import {Drawer} from '../../components/Drawer';
import {Button} from '../../components/Button';
import {Banner} from '../../components/Banner';
import {ConfirmDialog} from '../../components/ConfirmDialog';
import {AddMembersDialog} from './AddMembersDialog';
import {TransferOwnershipDialog} from './TransferOwnershipDialog';
import {MembersList} from './MembersList';
import {RefreshConnectionsButton} from './RefreshConnectionsButton';
import {FeatureGate} from '../feature-flags';
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
  onTransferOwnership: (newOwner: string) => void;
};

/**
 * Owner-only Manage-members drawer: lists current members (owner marked, never
 * removable) with Add, per-member Remove, and per-member Make-owner. All changes are async pipeline requests
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
  onRemoveMembers,
  onTransferOwnership
}: Props) {
  const [addOpen, setAddOpen] = useState(false);
  const [removing, setRemoving] = useState<string | null>(null);
  const [transferring, setTransferring] = useState<string | null>(null);

  const handleAdd = (toAdd: string[]) => {
    setAddOpen(false);
    onAddMembers(toAdd);
  };

  const confirmTransfer = () => {
    if (!transferring) return;
    const target = transferring;
    setTransferring(null);
    onTransferOwnership(target);
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
      mobileVariant="full-height"
      headerAccessory={
        <div className="ml-2 flex flex-none items-center gap-1.5">
          <RefreshConnectionsButton
            refreshing={refreshing}
            onRefresh={onRefresh}
          />
          <FeatureGate flag="sharedWorkspaces">
            <Button
              variant="primary"
              size="sm"
              onClick={() => setAddOpen(true)}
              disabled={busy}>
              Add members
            </Button>
          </FeatureGate>
        </div>
      }
      // no `closeOnEscape` gate — `useEscapeKey` dispatches by tree
      // depth, so a dialog opened from inside this drawer takes Escape on its own.
    >
      {unavailable && (
        <Banner variant="info">
          Member details aren&rsquo;t available yet — add or remove a member, then Refresh shared spaces to load the
          list.
        </Banner>
      )}

      <MembersList
        owner={owner}
        members={members}
        onRemove={setRemoving}
        onTransfer={setTransferring}
        busy={busy}
      />

      <p className="text-xs text-text-3">
        A <span className="font-medium text-text-2">Pending</span> member has been added but hasn&rsquo;t opened this
        space in Files yet; they become <span className="font-medium text-text-2">Active</span> once they do. Use
        Refresh to check for updates.
      </p>

      {addOpen && (
        <AddMembersDialog
          busy={busy}
          existing={members.map((m) => m.username)}
          onAdd={handleAdd}
          onCancel={() => setAddOpen(false)}
        />
      )}
      {transferring && (
        <TransferOwnershipDialog
          space={space}
          newOwner={transferring}
          busy={busy}
          onConfirm={confirmTransfer}
          onCancel={() => setTransferring(null)}
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
            lose access to its files and tables. The shared data isn&rsquo;t deleted.
          </p>
        </ConfirmDialog>
      )}
    </Drawer>
  );
}
