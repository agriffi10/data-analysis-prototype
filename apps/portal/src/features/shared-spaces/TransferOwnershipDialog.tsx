import {ConfirmDialog} from '../../components/ConfirmDialog';

type Props = {
  space: string;
  newOwner: string;
  busy?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
};

/**
 * Owner's confirm to hand a shared space to one of its members.
 *
 * Built on `ConfirmDialog` rather than a form dialog, and with no type-the-name gate: unlike
 * deleting, a transfer destroys nothing and the new owner can hand it straight back, so the
 * friction a delete earns would be friction for its own sake here. What the copy does have to
 * carry is the half users get wrong — that they keep their access and lose only the ability to
 * manage the space, and that undoing it is no longer their call to make.
 */
export function TransferOwnershipDialog({space, newOwner, busy = false, onConfirm, onCancel}: Props) {
  return (
    <ConfirmDialog
      title="Transfer ownership"
      ariaLabel={`Transfer ownership of ${space} to ${newOwner}`}
      confirmLabel="Transfer"
      busy={busy}
      busyLabel="Transferring…"
      onConfirm={onConfirm}
      onCancel={onCancel}>
      <p className="mt-2 text-sm text-text-2">
        Make <span className="font-mono">{newOwner}</span> the owner of <span className="font-mono">{space}</span>?
        They&rsquo;ll be able to add and remove members and delete the space.
      </p>
      <p className="mt-2 text-sm text-text-2">
        You&rsquo;ll stay a member and keep access to all its files and tables, but you won&rsquo;t be able to manage it
        any more — only {newOwner} can transfer it back.
      </p>
    </ConfirmDialog>
  );
}
