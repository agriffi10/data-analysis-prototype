import {ConfirmDialog} from '../../components/ConfirmDialog';

type Props = {
  space: string;
  busy?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
};

// SPEC-054 FR-001: a member's confirm to leave a shared space. Leaving only
// revokes the member's own access (slot + cache + registry membership) — no shared
// data is deleted (everyone else keeps access), so a plain danger confirm fits
// (contrast the owner's irreversible cascade in DeleteSharedSpaceDialog). Owners
// are never shown this — they delete instead (the action is owner-gated upstream).
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
