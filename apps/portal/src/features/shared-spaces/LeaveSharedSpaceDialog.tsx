import {ConfirmDialog} from '../../components/ConfirmDialog';

type Props = {
  space: string;
  busy?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
};

/**
 * Member's confirm to leave a shared space. Leaving only revokes the member's own
 * access — no shared data is deleted — so a plain danger confirm fits (contrast the
 * owner's type-the-name confirm in DeleteSharedSpaceDialog). Owners never see this;
 * the action is owner-gated upstream.
 */
export function LeaveSharedSpaceDialog({space, busy = false, onConfirm, onCancel}: Props) {
  return (
    <ConfirmDialog
      title="Leave shared space"
      ariaLabel={`Leave ${space}`}
      tone="danger"
      confirmVariant="danger"
      confirmLabel="Leave"
      busy={busy}
      busyLabel="Leaving…"
      onConfirm={onConfirm}
      onCancel={onCancel}>
      <p className="mt-2 text-sm text-text-2">
        Leave <span className="font-mono">{space}</span>? You&apos;ll lose access to its files and tables. They are not
        deleted — everyone else keeps access.
      </p>
    </ConfirmDialog>
  );
}
