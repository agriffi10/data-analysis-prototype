import {ConfirmDialog} from '../../components/ConfirmDialog';

type Props = {
  onConfirm: () => void;
  onCancel: () => void;
};

// SPEC-040 FR-003: warn-and-confirm before Clear wipes the editor. Thin wrapper
// over the shared ConfirmDialog (no undo → focus defaults to Cancel).
export function ClearQueryDialog({onConfirm, onCancel}: Props) {
  return (
    <ConfirmDialog
      title="Clear the query?"
      ariaLabel="Confirm clear query"
      confirmLabel="Clear"
      confirmVariant="danger"
      tone="danger"
      irreversible
      onConfirm={onConfirm}
      onCancel={onCancel}>
      <p className="mt-3 text-sm text-text-2">This empties the editor and discards the draft saved for this session.</p>
    </ConfirmDialog>
  );
}
